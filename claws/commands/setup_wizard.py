from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt

from claws.commands import setup_anthropic, setup_github, setup_telegram

console = Console()


EXPLANATIONS = {
    "intro": (
        "Welcome to the claws setup wizard.\n\n"
        "claws orchestrates an AI-assisted GitHub workflow that polls a Project board, "
        "runs Claude Code on issues in the Ready column, opens pull requests for review, "
        "and notifies you on Telegram. To work, claws needs four credentials wired into "
        "AWS SSM Parameter Store (under /claws/<project>/...). This wizard collects each "
        "one, explains exactly what it is used for, validates it live, and writes it to "
        "SSM. Nothing is sent anywhere except to the upstream provider for validation."
    ),
    "anthropic": (
        "Anthropic API key\n\n"
        "Used by the OpenClaw gateway on the EC2 box to run Claude Code on your behalf "
        "(model invocations for the autonomous agent that works your issues). The key is "
        "stored encrypted in SSM at /claws/<project>/anthropic/api-key and fetched by the "
        "gateway at runtime. It never leaves your AWS account except as outbound HTTPS to "
        "api.anthropic.com when the agent runs. We validate it by calling Anthropic's "
        "/v1/models endpoint."
    ),
    "github": (
        "GitHub credentials\n\n"
        "claws needs a Personal Access Token with 'repo' and 'project' scopes so the "
        "poller can: read your Project board, move cards between Status columns, create "
        "PRs, and comment on issues. If you already have the GitHub CLI authenticated "
        "locally we can mint a token via 'gh auth token' for convenience; otherwise paste "
        "a manually-created classic PAT (https://github.com/settings/tokens). The token "
        "is stored encrypted in SSM at /claws/<project>/github/token and also installed "
        "as a repo secret (PROJECT_PAT) so workflows can use it."
    ),
    "telegram": (
        "Telegram bot\n\n"
        "claws sends you notifications (new issue picked up, PR ready, blocked, etc.) "
        "via a Telegram bot you control. You create the bot by messaging @BotFather on "
        "Telegram, sending /newbot, and following the prompts -- BotFather hands you a "
        "token like 123456:ABC-DEF.... To find your numeric Telegram user ID (so the bot "
        "only responds to you) message @userinfobot. The token and allowed user IDs are "
        "stored in SSM at /claws/<project>/telegram/{bot-token,allowed-user-ids} and "
        "validated by calling Telegram's getMe API."
    ),
    "project": (
        "GitHub Project (v2)\n\n"
        "claws drives a Project board with a Status field containing columns: Ready, "
        "In Progress, In Review, Blocked, Approved. The poller polls the Ready column "
        "for issues to work on and moves cards through the lifecycle. You can point "
        "claws at an existing v2 project or have the wizard create a fresh one (a name "
        "you supply) and add the required Status options. We will write the project's "
        "GraphQL node ID, number, status-field ID, and per-status option IDs to SSM."
    ),
}


def _validate_anthropic_key(key: str) -> bool:
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        headers={
            "X-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError:
        return False
    except urllib.error.URLError:
        return False


def _validate_telegram_token(token: str) -> Optional[dict]:
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getMe")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    except urllib.error.URLError:
        return None
    except json.JSONDecodeError:
        return None
    if not payload["ok"]:
        return None
    return payload["result"]


def _validate_github_token(token: str) -> Optional[dict]:
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    except urllib.error.URLError:
        return None
    except json.JSONDecodeError:
        return None


def _graphql(query: str, variables: dict, env: dict) -> dict:
    payload = json.dumps({"query": query, "variables": variables})
    result = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        console.print(f"[red]GraphQL error:[/] {result.stderr}")
        raise typer.Exit(1)
    return json.loads(result.stdout)


_GQL_OWNER_ID = """
query($owner: String!) {
  repositoryOwner(login: $owner) { __typename id }
}
"""

_GQL_LIST_USER_PROJECTS = """
query($owner: String!) {
  user(login: $owner) {
    projectsV2(first: 50) { nodes { id number title } }
  }
}
"""

_GQL_LIST_ORG_PROJECTS = """
query($owner: String!) {
  organization(login: $owner) {
    projectsV2(first: 50) { nodes { id number title } }
  }
}
"""

_GQL_CREATE_PROJECT = """
mutation($ownerId: ID!, $title: String!) {
  createProjectV2(input: { ownerId: $ownerId, title: $title }) {
    projectV2 { id number title }
  }
}
"""


def _create_project(owner: str, title: str, env: dict) -> dict:
    owner_data = _graphql(_GQL_OWNER_ID, {"owner": owner}, env)
    owner_id = owner_data["data"]["repositoryOwner"]["id"]
    resp = _graphql(_GQL_CREATE_PROJECT, {"ownerId": owner_id, "title": title}, env)
    return resp["data"]["createProjectV2"]["projectV2"]


def _list_projects(owner: str, env: dict) -> list:
    owner_data = _graphql(_GQL_OWNER_ID, {"owner": owner}, env)
    kind = owner_data["data"]["repositoryOwner"]["__typename"]
    query = _GQL_LIST_ORG_PROJECTS if kind == "Organization" else _GQL_LIST_USER_PROJECTS
    data = _graphql(query, {"owner": owner}, env)
    container = data["data"]["organization" if kind == "Organization" else "user"]
    return container["projectsV2"]["nodes"]


def _select_or_create_project(owner: str, env: dict) -> dict:
    choice = Prompt.ask(
        "Use [bold]existing[/] project or [bold]create[/] a new one?",
        choices=["use_existing", "create"],
        default="use_existing",
    )
    if choice == "create":
        title = Prompt.ask("New project title")
        console.print(f"[bold]Creating project '{title}' under {owner}...[/]")
        proj = _create_project(owner, title, env)
        console.print(f"[green]Created project #{proj['number']}: {proj['title']}[/]")
        return proj

    projects = _list_projects(owner, env)
    if not projects:
        console.print(f"[yellow]No existing projects found under {owner}. Switching to create.[/]")
        title = Prompt.ask("New project title")
        proj = _create_project(owner, title, env)
        console.print(f"[green]Created project #{proj['number']}: {proj['title']}[/]")
        return proj

    console.print("[bold]Available projects:[/]")
    for proj in projects:
        console.print(f"  [cyan]#{proj['number']}[/] {proj['title']}")
    number = IntPrompt.ask("Project number")
    match = next((p for p in projects if p["number"] == number), None)
    if match is None:
        console.print(f"[red]No project with number {number} found under {owner}.[/]")
        raise typer.Exit(1)
    return match


def _collect_anthropic_key() -> str:
    env_key = os.environ["ANTHROPIC_API_KEY"] if "ANTHROPIC_API_KEY" in os.environ else None
    if env_key:
        masked = env_key[:10] + "..." if len(env_key) > 10 else env_key
        use_env = Confirm.ask(
            f"Found ANTHROPIC_API_KEY in environment ([dim]{masked}[/]). Use this key?",
            default=True,
        )
        if use_env:
            console.print("[bold]Validating Anthropic key...[/]")
            if _validate_anthropic_key(env_key):
                console.print("[green]Anthropic key is valid.[/]")
                return env_key
            console.print("[red]Anthropic key from environment failed validation.[/]")

    for _ in range(3):
        key = Prompt.ask("Paste your Anthropic API key", password=True)
        console.print("[bold]Validating...[/]")
        if _validate_anthropic_key(key):
            console.print("[green]Anthropic key is valid.[/]")
            return key
        console.print("[red]Invalid key. Try again.[/]")
    console.print("[red]Anthropic key validation failed after 3 attempts. Aborting.[/]")
    raise typer.Exit(1)


def _collect_github_token() -> str:
    auth_status = subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True
    )
    gh_logged_in = auth_status.returncode == 0

    if gh_logged_in:
        use_gh = Confirm.ask(
            "GitHub CLI is authenticated. Use 'gh auth token' to obtain a token?",
            default=True,
        )
        if use_gh:
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True
            )
            if result.returncode == 0:
                token = result.stdout.strip()
                console.print("[bold]Validating GitHub token...[/]")
                user = _validate_github_token(token)
                if user:
                    console.print(f"[green]Authenticated as {user['login']}.[/]")
                    return token
                console.print("[yellow]gh-issued token failed validation; falling back to manual.[/]")
            else:
                console.print(f"[yellow]gh auth token failed: {result.stderr.strip()}[/]")
    else:
        console.print("[yellow]gh CLI not authenticated.[/] Run 'gh auth login' if you want the wizard to mint a token for you next time.")

    for _ in range(3):
        token = Prompt.ask(
            "Paste a GitHub Personal Access Token (scopes: repo, project)",
            password=True,
        )
        console.print("[bold]Validating GitHub token...[/]")
        user = _validate_github_token(token)
        if user:
            console.print(f"[green]Authenticated as {user['login']}.[/]")
            return token
        console.print("[red]Invalid token. Try again.[/]")
    console.print("[red]GitHub token validation failed after 3 attempts. Aborting.[/]")
    raise typer.Exit(1)


def _collect_telegram() -> tuple[str, str]:
    console.print(Panel.fit(
        "1. Open Telegram and message [bold]@BotFather[/].\n"
        "2. Send [cyan]/newbot[/] and follow the prompts to name your bot.\n"
        "3. BotFather will reply with a token like [dim]123456:ABC-DEF...[/].\n"
        "4. To find your numeric Telegram user ID, message [bold]@userinfobot[/].",
        title="Telegram setup",
    ))

    choice = Prompt.ask(
        "Have you created the bot and have a token?",
        choices=["manual", "skip"],
        default="manual",
    )
    if choice == "skip":
        console.print("[red]Telegram setup requires a bot token. Aborting.[/]")
        raise typer.Exit(1)

    for _ in range(3):
        token = Prompt.ask("Paste your Telegram bot token", password=True)
        console.print("[bold]Validating Telegram token...[/]")
        info = _validate_telegram_token(token)
        if info:
            console.print(f"[green]Bot @{info['username']} (id={info['id']}) validated.[/]")
            break
        console.print("[red]Invalid token. Try again.[/]")
    else:
        console.print("[red]Telegram token validation failed after 3 attempts. Aborting.[/]")
        raise typer.Exit(1)

    user_ids = Prompt.ask(
        "Comma-separated Telegram user IDs allowed to talk to the bot"
    )
    cleaned = ",".join(part.strip() for part in user_ids.split(",") if part.strip())
    if not cleaned:
        console.print("[red]At least one allowed user ID is required.[/]")
        raise typer.Exit(1)
    return token, cleaned


def _invoke_setup_anthropic(project: str, region: str, api_key: str):
    setup_anthropic.run(project=project, api_key=api_key, region=region)


def _invoke_setup_github(
    project: str,
    region: str,
    token: str,
    owner: str,
    repo: str,
    project_number: int,
):
    setup_github.run(
        project=project,
        token=token,
        owner=owner,
        repo=repo,
        project_number=project_number,
        region=region,
        yes=True,
    )


def _invoke_setup_telegram(
    project: str, region: str, bot_token: str, allowed_user_ids: str
):
    setup_telegram.run(
        project=project,
        bot_token=bot_token,
        allowed_user_ids=allowed_user_ids,
        region=region,
    )


def run(
    project: Optional[str] = typer.Option(None, help="Project name (used as SSM prefix)"),
    region: Optional[str] = typer.Option(None, help="AWS region"),
):
    from claws.config import resolve
    try:
        project, region = resolve(project, region)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    console.print(Panel.fit(EXPLANATIONS["intro"], title="claws setup wizard"))
    console.print(f"[dim]Project: {project} | Region: {region}[/]\n")

    console.print(Panel.fit(EXPLANATIONS["anthropic"], title="Step 1/4 - Anthropic"))
    anthropic_key = _collect_anthropic_key()

    console.print(Panel.fit(EXPLANATIONS["github"], title="Step 2/4 - GitHub"))
    gh_token = _collect_github_token()
    env = {**os.environ, "GH_TOKEN": gh_token}

    owner = Prompt.ask("GitHub owner (org or user) that owns the repo and project")
    repo = Prompt.ask("Repository (org/name format)", default=f"{owner}/claws")

    console.print(Panel.fit(EXPLANATIONS["project"], title="Step 3/4 - GitHub Project"))
    proj = _select_or_create_project(owner, env)

    console.print(Panel.fit(EXPLANATIONS["telegram"], title="Step 4/4 - Telegram"))
    bot_token, allowed_user_ids = _collect_telegram()

    console.print("\n[bold]Summary[/]")
    console.print(f"  Project       : {project} ({region})")
    console.print(f"  Anthropic key : [green]validated[/]")
    console.print(f"  GitHub owner  : {owner}")
    console.print(f"  GitHub repo   : {repo}")
    console.print(f"  GH project    : #{proj['number']} {proj['title']}")
    console.print(f"  Telegram bot  : [green]validated[/]")
    console.print(f"  Allowed users : {allowed_user_ids}")

    if not Confirm.ask("Write all credentials to SSM now?", default=True):
        console.print("[yellow]Aborted by user.[/]")
        raise typer.Exit(1)

    console.print("\n[bold]Writing Anthropic config...[/]")
    _invoke_setup_anthropic(project, region, anthropic_key)

    console.print("\n[bold]Writing GitHub config...[/]")
    _invoke_setup_github(project, region, gh_token, owner, repo, proj["number"])

    console.print("\n[bold]Writing Telegram config...[/]")
    _invoke_setup_telegram(project, region, bot_token, allowed_user_ids)

    console.print("\n[green]Setup wizard complete.[/]")
    console.print(f"Run [cyan]claws status --project {project}[/] to verify.")
