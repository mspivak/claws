import json
import subprocess
from datetime import datetime, timezone

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


def _relative(ms: int) -> str:
    now = datetime.now(timezone.utc).timestamp() * 1000
    diff = int((ms - now) / 1000)
    if diff < 0:
        secs = -diff
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        return f"{secs // 3600}h ago"
    if diff < 60:
        return f"in {diff}s"
    return f"in {diff // 60}m"


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
        color = "green" if gw.get("ok") else "red"
        console.print(f"[bold]Gateway:[/] [{color}]{'ok' if gw.get('ok') else 'error'}[/]")
    except Exception:
        console.print("[bold]Gateway:[/] [red]unreachable[/]")

    cron = _ssh(ip, "openclaw cron list --json 2>/dev/null || echo '{}'")
    try:
        jobs = json.loads(cron).get("jobs", [])
        poller = next((j for j in jobs if j.get("name") == "github-poller"), None)
        if poller:
            last_ms = poller.get("state", {}).get("lastRunAtMs")
            next_ms = poller.get("state", {}).get("nextRunAtMs")
            last_str = _relative(last_ms) if last_ms else "never"
            next_str = _relative(next_ms) if next_ms else "unknown"
            console.print(f"[bold]Poller:[/] last ran {last_str}, next {next_str}")
        else:
            console.print("[bold]Poller:[/] [yellow]not configured[/]")
    except Exception:
        console.print("[bold]Poller:[/] [yellow]unknown[/]")

    ssm = boto3.client("ssm", region_name=region)
    repo = ""
    try:
        repo = ssm.get_parameter(Name=f"/claws/{project}/github/repo")["Parameter"]["Value"]
    except Exception:
        pass

    sessions_raw = _ssh(ip, "openclaw gateway call sessions.list --json 2>/dev/null")
    state_raw = _ssh(ip, "cat ~/.openclaw/poller-state.json 2>/dev/null || echo '{}'")
    try:
        all_sessions = json.loads(sessions_raw).get("sessions", [])
        active_keys = {s["key"] for s in all_sessions}
        state = json.loads(state_raw).get("sessions", {})
        now_ms = datetime.now(timezone.utc).timestamp() * 1000
        acp = [
            s for s in all_sessions
            if "poller-issue" in (s.get("label") or "")
            and (s["key"] in state or (now_ms - s["updatedAt"]) < 30 * 60 * 1000)
        ]
        seen_issues = set()
        deduped = []
        for s in sorted(acp, key=lambda x: x["updatedAt"], reverse=True):
            issue_num = s.get("label", "").replace("poller-issue-", "").split("-")[0]
            if issue_num not in seen_issues:
                seen_issues.add(issue_num)
                deduped.append(s)

        console.print(f"\n[bold]Sessions:[/] {len(state)} active")
        if deduped:
            t = Table("Issue", "Branch", "Status", "Last update", box=None, pad_edge=False)
            for s in deduped:
                label = s.get("label", "")
                issue_num = label.replace("poller-issue-", "").split("-")[0]
                issue_url = f"https://github.com/{repo}/issues/{issue_num}" if repo else f"#{issue_num}"
                branch = f"issue-{issue_num}"
                running = s["key"] in state
                status_str = "[green]running[/]" if running else "[dim]finished[/]"
                updated = _relative(s["updatedAt"])
                t.add_row(issue_url, branch, status_str, updated)
            console.print(t)
    except Exception:
        console.print("[bold]Sessions:[/] [yellow]unknown[/]")

    keys = ["github/token", "github/repo", "github/project-id",
            "anthropic/api-key", "telegram/bot-token"]
    console.print("\n[bold]Secrets:[/]")
    for key in keys:
        try:
            ssm.get_parameter(Name=f"/claws/{project}/{key}", WithDecryption=False)
            console.print(f"  [green]✓[/] {key}")
        except ssm.exceptions.ParameterNotFound:
            console.print(f"  [red]✗[/] {key}")
