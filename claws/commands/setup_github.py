import json
import os
import subprocess

import boto3
import typer
from rich.console import Console
from rich.prompt import Confirm

console = Console()

_GQL_PROJECT_ORG = """
query($owner: String!, $number: Int!) {
  organization(login: $owner) {
    projectV2(number: $number) {
      id
      fields(first: 50) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id
            name
            options { id name }
          }
        }
      }
    }
  }
}
"""

_GQL_PROJECT_USER = """
query($owner: String!, $number: Int!) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      fields(first: 50) {
        nodes {
          ... on ProjectV2SingleSelectField {
            id
            name
            options { id name }
          }
        }
      }
    }
  }
}
"""

_GQL_OWNER_TYPE = """
query($owner: String!) {
  repositoryOwner(login: $owner) { __typename }
}
"""

_GQL_UPDATE_FIELD = """
mutation($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
  updateProjectV2Field(input: {
    fieldId: $fieldId
    singleSelectOptions: $options
  }) {
    projectV2Field {
      ... on ProjectV2SingleSelectField {
        id name options { id name }
      }
    }
  }
}
"""

_REQUIRED_OPTIONS = [
    {"name": "Ready",       "color": "GREEN",  "description": ""},
    {"name": "In Progress", "color": "YELLOW", "description": ""},
    {"name": "In Review",   "color": "BLUE",   "description": ""},
    {"name": "Blocked",     "color": "RED",    "description": ""},
]

_OPTIONAL_OPTIONS = ["Approved"]


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


def _put_ssm(ssm, name: str, value: str, secure: bool):
    ssm.put_parameter(
        Name=name,
        Value=value,
        Type="SecureString" if secure else "String",
        Overwrite=True,
    )


def run(
    project: str = typer.Option(None),
    token: str = typer.Option(..., help="GitHub PAT (repo + project scopes)"),
    owner: str = typer.Option(..., help="GitHub org or user name"),
    repo: str = typer.Option(...),
    project_number: int = typer.Option(...),
    region: str = typer.Option(None, help="AWS region"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-create missing status options"),
):
    from claws.config import resolve
    try:
        project, region = resolve(project, region)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    env = {**os.environ, "GH_TOKEN": token}

    owner_type_data = _graphql(_GQL_OWNER_TYPE, {"owner": owner}, env)
    owner_type = owner_type_data["data"]["repositoryOwner"]["__typename"]
    console.print(f"[bold]Fetching project #{project_number} from {owner_type.lower()} {owner}...[/]")

    query = _GQL_PROJECT_ORG if owner_type == "Organization" else _GQL_PROJECT_USER
    data = _graphql(query, {"owner": owner, "number": project_number}, env)
    project_data = data["data"][owner_type.lower()]["projectV2"]
    project_id = project_data["id"]
    console.print(f"Project ID: {project_id}")

    status_field = next(
        (n for n in project_data["fields"]["nodes"] if n and n.get("name") == "Status"),
        None,
    )
    if not status_field:
        console.print("[red]No 'Status' field found in project.[/]")
        raise typer.Exit(1)

    field_id = status_field["id"]
    options = {opt["name"]: opt["id"] for opt in status_field["options"]}
    console.print(f"Status options found: {list(options.keys())}")

    missing = [o["name"] for o in _REQUIRED_OPTIONS if o["name"] not in options]
    if missing:
        console.print(f"[yellow]Missing options: {missing}[/]")
        if not yes and not Confirm.ask("Overwrite Status field with required options?", default=True):
            console.print("[red]Aborting — required options are missing.[/]")
            raise typer.Exit(1)
        resp = _graphql(_GQL_UPDATE_FIELD, {"fieldId": field_id, "options": _REQUIRED_OPTIONS}, env)
        updated = resp["data"]["updateProjectV2Field"]["projectV2Field"]
        options = {opt["name"]: opt["id"] for opt in updated["options"]}
        console.print(f"[green]Status field updated: {list(options.keys())}[/]")

    prefix = f"/claws/{project}"
    ssm = boto3.client("ssm", region_name=region)

    params = {
        f"{prefix}/github/token": (token, True),
        f"{prefix}/github/org": (owner, False),
        f"{prefix}/github/repo": (repo, False),
        f"{prefix}/github/project-number": (str(project_number), False),
        f"{prefix}/github/project-id": (project_id, False),
        f"{prefix}/github/status-field-id": (field_id, False),
        f"{prefix}/github/status-ready": (options["Ready"], False),
        f"{prefix}/github/status-in-progress": (options["In Progress"], False),
        f"{prefix}/github/status-blocked": (options["Blocked"], False),
        f"{prefix}/github/status-in-review": (options["In Review"], False),
    }

    if "Approved" in options:
        params[f"{prefix}/github/status-approved"] = (options["Approved"], False)
    else:
        console.print(
            "[yellow]Warning:[/] no 'Approved' option in project Status field — "
            "skipping /github/status-approved. The poller will not be able to detect "
            "the terminal approval state. If your project uses 'Done' or another name, "
            "rename it to 'Approved' or set the SSM param manually."
        )

    console.print("[bold]Writing SSM parameters...[/]")
    for name, (value, secure) in params.items():
        _put_ssm(ssm, name, value, secure)
        console.print(f"  [green]✓[/] {name}")

    console.print("[bold]Setting GitHub Actions secrets and variables...[/]")
    for name, value in [
        ("PROJECT_PAT", token),
    ]:
        result = subprocess.run(
            ["gh", "secret", "set", name, "--repo", repo, "--body", value],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            console.print(f"[yellow]Warning: could not set secret {name}: {result.stderr.strip()}[/]")
        else:
            console.print(f"  [green]✓[/] secret {name}")

    variables = [
        ("CLAWS_PROJECT_NODE_ID", project_id),
        ("CLAWS_STATUS_FIELD_ID", field_id),
    ]
    if "Approved" in options:
        variables.append(("CLAWS_STATUS_APPROVED_ID", options["Approved"]))

    for name, value in variables:
        result = subprocess.run(
            ["gh", "variable", "set", name, "--repo", repo, "--body", value],
            capture_output=True, text=True, env=env,
        )
        if result.returncode != 0:
            console.print(f"[yellow]Warning: could not set variable {name}: {result.stderr.strip()}[/]")
        else:
            console.print(f"  [green]✓[/] variable {name}")

    console.print(f"[bold]Done.[/] Run [cyan]claws status --project {project}[/] to verify.")
