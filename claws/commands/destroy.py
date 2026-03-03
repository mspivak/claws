from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm

console = Console()

TERRAFORM_DIR = Path(__file__).parent.parent.parent / "terraform"


def run(
    project: Optional[str] = typer.Option(None),
    region: Optional[str] = typer.Option(None, help="AWS region"),
):
    from claws.config import resolve
    try:
        project, region = resolve(project, region)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    if not Confirm.ask(
        f"[bold red]Destroy all infrastructure for project '{project}'?[/]",
        default=False,
    ):
        console.print("Aborted.")
        raise typer.Exit(0)

    tf_vars = [
        f"-var=project_name={project}",
        f"-var=aws_region={region}",
        "-var=github_repo=placeholder",
    ]

    result = subprocess.run(
        ["terraform", "destroy", *tf_vars],
        cwd=TERRAFORM_DIR,
    )
    if result.returncode != 0:
        raise typer.Exit(result.returncode)
