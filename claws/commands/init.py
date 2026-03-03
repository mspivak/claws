import subprocess
import sys
from pathlib import Path

import boto3
import typer
from rich.console import Console

console = Console()

TERRAFORM_DIR = Path(__file__).parent.parent.parent / "terraform"


def _check_aws_credentials():
    sts = boto3.client("sts")
    try:
        identity = sts.get_caller_identity()
        console.print(f"[green]AWS identity:[/] {identity['Arn']}")
    except Exception as exc:
        console.print(f"[red]AWS credentials error:[/] {exc}")
        raise typer.Exit(1)


def _run(cmd: list[str], cwd: Path):
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise typer.Exit(result.returncode)


def run(
    project: str = typer.Option(..., help="Project name (used as SSM prefix and name tag)"),
    repo: str = typer.Option(..., help="GitHub repo to clone (org/name)"),
    region: str = typer.Option(..., help="AWS region"),
    instance_type: str = typer.Option("t3.nano", help="EC2 instance type"),
    ssh_public_key_path: str = typer.Option("~/.ssh/id_rsa.pub"),
):
    _check_aws_credentials()

    tf_vars = [
        f"-var=project_name={project}",
        f"-var=aws_region={region}",
        f"-var=github_repo={repo}",
        f"-var=instance_type={instance_type}",
        f"-var=ssh_public_key_path={ssh_public_key_path}",
    ]

    console.print("[bold]Initializing Terraform...[/]")
    _run(["terraform", "init"], cwd=TERRAFORM_DIR)

    console.print("[bold]Applying Terraform...[/]")
    _run(["terraform", "apply", "-auto-approve", *tf_vars], cwd=TERRAFORM_DIR)

    result = subprocess.run(
        ["terraform", "output", "-raw", "ssh_command"],
        cwd=TERRAFORM_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print(f"\n[green]SSH:[/] {result.stdout.strip()}")
