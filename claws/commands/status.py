import json
import subprocess

import boto3
import typer
from rich.console import Console
from rich.table import Table

console = Console()


def _get_instance(project: str, region: str) -> dict | None:
    ec2 = boto3.client("ec2", region_name=region)
    resp = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Project", "Values": [project]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    if not resp["Reservations"]:
        return None
    return resp["Reservations"][0]["Instances"][0]


def _ssh(ip: str, cmd: str) -> str:
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5",
         f"ec2-user@{ip}", cmd],
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def run(
    project: str = typer.Option(...),
    region: str = typer.Option(..., help="AWS region"),
):
    instance = _get_instance(project, region)
    if not instance:
        console.print(f"[red]No running instance for project '{project}'[/]")
        raise typer.Exit(1)

    ip = instance["PublicIpAddress"]
    instance_id = instance["InstanceId"]
    console.print(f"[bold]Instance:[/] {instance_id} ({ip})")

    gateway = _ssh(ip, "openclaw gateway health --json 2>/dev/null")
    try:
        gw = json.loads(gateway)
        status = "ok" if gw.get("ok") else "error"
        color = "green" if gw.get("ok") else "red"
        console.print(f"[bold]Gateway:[/] [{color}]{status}[/]")
    except Exception:
        console.print("[bold]Gateway:[/] [red]unreachable[/]")

    cron = _ssh(ip, "openclaw cron list --json 2>/dev/null || echo '{}'")
    try:
        jobs = json.loads(cron).get("jobs", [])
        poller = next((j for j in jobs if j.get("name") == "github-poller"), None)
        if poller:
            last = poller.get("state", {}).get("lastRunAtMs")
            nxt = poller.get("state", {}).get("nextRunAtMs")
            console.print(f"[bold]Poller:[/] enabled  last={last}  next={nxt}")
        else:
            console.print("[bold]Poller:[/] [yellow]cron job not found[/]")
    except Exception:
        console.print("[bold]Poller:[/] [yellow]unknown[/]")

    sessions_raw = _ssh(ip, "openclaw gateway call sessions.list --json 2>/dev/null")
    try:
        sessions = json.loads(sessions_raw).get("sessions", [])
        acp = [s for s in sessions if "poller-issue" in (s.get("label") or "")]
        state_raw = _ssh(ip, "cat ~/.openclaw/poller-state.json 2>/dev/null || echo '{}'")
        state = json.loads(state_raw).get("sessions", {})
        console.print(f"[bold]Active sessions:[/] {len(state)}  (tracked in poller-state.json)")
        if acp:
            t = Table("label", "updated", box=None, pad_edge=False)
            for s in acp:
                import datetime
                ts = datetime.datetime.fromtimestamp(s["updatedAt"] / 1000).strftime("%H:%M:%S")
                t.add_row(s["label"], ts)
            console.print(t)
    except Exception:
        console.print("[bold]Sessions:[/] [yellow]unknown[/]")

    ssm = boto3.client("ssm", region_name=region)
    prefix = f"/claws/{project}"
    keys = ["github/token", "github/repo", "github/project-id",
            "anthropic/api-key", "telegram/bot-token"]
    console.print("\n[bold]SSM parameters:[/]")
    for key in keys:
        name = f"{prefix}/{key}"
        try:
            ssm.get_parameter(Name=name, WithDecryption=False)
            console.print(f"  [green]✓[/] {name}")
        except ssm.exceptions.ParameterNotFound:
            console.print(f"  [red]✗[/] {name}")
