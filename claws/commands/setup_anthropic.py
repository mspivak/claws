from __future__ import annotations

import subprocess
from typing import Optional

import boto3
import typer
from rich.console import Console

console = Console()


def _get_instance_ip(project: str, region: str) -> Optional[str]:
    ec2 = boto3.client("ec2", region_name=region)
    resp = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [project]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    reservations = resp["Reservations"]
    if not reservations:
        return None
    return reservations[0]["Instances"][0]["PublicIpAddress"]


def run(
    project: Optional[str] = typer.Option(None),
    api_key: str = typer.Option(..., envvar="ANTHROPIC_API_KEY", help="Anthropic API key"),
    region: Optional[str] = typer.Option(None, help="AWS region"),
):
    from claws.config import resolve
    try:
        project, region = resolve(project, region)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    ssm = boto3.client("ssm", region_name=region)
    ssm.put_parameter(
        Name=f"/claws/{project}/anthropic/api-key",
        Value=api_key,
        Type="SecureString",
        Overwrite=True,
    )
    console.print(f"  [green]✓[/] /claws/{project}/anthropic/api-key")

    ip = _get_instance_ip(project, region)
    if ip:
        console.print("[bold]Restarting OpenClaw gateway to pick up new key...[/]")
        subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", f"ec2-user@{ip}",
             "systemctl --user restart openclaw-gateway.service"],
            capture_output=True,
        )
        console.print("[green]Done.[/]")
    else:
        console.print("[yellow]No running instance found — restart the gateway manually.[/]")
