import subprocess

import boto3
import typer
from rich.console import Console

console = Console()


def _ssh(host: str, cmd: str):
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"ec2-user@{host}", cmd],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]SSH error:[/] {result.stderr}")
        raise typer.Exit(1)
    return result.stdout.strip()


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
    bot_token: str = typer.Option(...),
    allowed_user_ids: str = typer.Option(..., help="Comma-separated numeric Telegram user IDs"),
    region: str = typer.Option(..., help="AWS region"),
):
    prefix = f"/claws/{project}"
    ssm = boto3.client("ssm", region_name=region)

    console.print("[bold]Writing SSM parameters...[/]")
    ssm.put_parameter(
        Name=f"{prefix}/telegram/bot-token",
        Value=bot_token,
        Type="SecureString",
        Overwrite=True,
    )
    console.print(f"  [green]✓[/] {prefix}/telegram/bot-token")

    ssm.put_parameter(
        Name=f"{prefix}/telegram/allowed-user-ids",
        Value=allowed_user_ids,
        Type="String",
        Overwrite=True,
    )
    console.print(f"  [green]✓[/] {prefix}/telegram/allowed-user-ids")

    console.print("[bold]Reloading OpenClaw config on EC2 instance...[/]")
    ip = _get_instance_ip(project, region)
    _ssh(ip, "openclaw gateway reload")
    console.print("[green]Done.[/]")
