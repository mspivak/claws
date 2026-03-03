import subprocess

import boto3
import typer
from rich.console import Console

console = Console()


def _get_instance_ip(project: str, region: str) -> str:
    ec2 = boto3.client("ec2", region_name=region)
    resp = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [project]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    reservations = resp["Reservations"]
    if not reservations:
        console.print(f"[red]No running instance found for project '{project}'[/]")
        raise typer.Exit(1)
    return reservations[0]["Instances"][0]["PublicIpAddress"]


def run(
    project: str = typer.Option(...),
    region: str = typer.Option(..., help="AWS region"),
):
    ip = _get_instance_ip(project, region)
    console.print(f"[bold]Instance:[/] {ip}")

    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"ec2-user@{ip}", "openclaw acp"],
        text=True,
    )
    if result.returncode != 0:
        raise typer.Exit(result.returncode)
