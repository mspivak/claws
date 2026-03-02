import json
import os
import subprocess

import boto3
import typer
from rich.console import Console
from rich.prompt import Confirm

console = Console()

_GQL_PROJECT = """
query($org: String!, $number: Int!) {
  organization(login: $org) {
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

_GQL_CREATE_OPTION = """
mutation($projectId: ID!, $fieldId: ID!, $name: String!) {
  createProjectV2FieldOption(input: {
    projectId: $projectId
    fieldId: $fieldId
    name: $name
  }) {
    option { id name }
  }
}
"""


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
    project: str = typer.Option(...),
    token: str = typer.Option(..., help="GitHub PAT (repo + project scopes)"),
    org: str = typer.Option(...),
    repo: str = typer.Option(...),
    project_number: int = typer.Option(...),
    region: str = typer.Option(..., help="AWS region"),
):
    env = {**os.environ, "GH_TOKEN": token}

    console.print(f"[bold]Fetching project #{project_number} from org {org}...[/]")

    data = _graphql(_GQL_PROJECT, {"org": org, "number": project_number}, env)
    project_data = data["data"]["organization"]["projectV2"]
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
    console.print(f"Status options: {list(options.keys())}")

    for name in ["Ready", "In Progress", "In Review", "Blocked"]:
        if name in options:
            continue
        console.print(f"[yellow]Status option '{name}' not found.[/]")
        if not Confirm.ask(f"Create '{name}' option?", default=True):
            console.print(f"[red]Aborting — '{name}' is required.[/]")
            raise typer.Exit(1)
        resp = _graphql(
            _GQL_CREATE_OPTION,
            {"projectId": project_id, "fieldId": field_id, "name": name},
            env,
        )
        new_opt = resp["data"]["createProjectV2FieldOption"]["option"]
        options[new_opt["name"]] = new_opt["id"]
        console.print(f"[green]Created '{name}': {new_opt['id']}[/]")

    prefix = f"/claws/{project}"
    ssm = boto3.client("ssm", region_name=region)

    params = {
        f"{prefix}/github/token": (token, True),
        f"{prefix}/github/org": (org, False),
        f"{prefix}/github/repo": (repo, False),
        f"{prefix}/github/project-number": (str(project_number), False),
        f"{prefix}/github/project-id": (project_id, False),
        f"{prefix}/github/status-field-id": (field_id, False),
        f"{prefix}/github/status-ready": (options["Ready"], False),
        f"{prefix}/github/status-in-progress": (options["In Progress"], False),
        f"{prefix}/github/status-blocked": (options["Blocked"], False),
        f"{prefix}/github/status-in-review": (options["In Review"], False),
    }

    console.print("[bold]Writing SSM parameters...[/]")
    for name, (value, secure) in params.items():
        _put_ssm(ssm, name, value, secure)
        console.print(f"  [green]✓[/] {name}")

    console.print(f"[bold]Done.[/] Run [cyan]claws status --project {project}[/] to verify.")
