from unittest.mock import MagicMock, patch

import pytest


def _captured_ssh_cmd(project, region, ip):
    """Run status.run() and return the SSH command that was passed to subprocess.run."""
    from claws.commands import status

    captured = {}

    def fake_subprocess_run(cmd, **kwargs):
        captured["cmd"] = cmd
        result = MagicMock()
        result.returncode = 0
        return result

    with (
        patch.object(status, "_get_instance_ip", return_value=ip),
        patch("claws.commands.status.subprocess.run", side_effect=fake_subprocess_run),
    ):
        from typer.testing import CliRunner
        from claws.main import app

        runner = CliRunner()
        runner.invoke(app, ["status", "--project", project, "--region", region])

    return captured.get("cmd", [])


def test_status_ssh_command_does_not_pass_status_argument():
    """openclaw acp must not receive 'status' as an argument."""
    cmd = _captured_ssh_cmd("claws", "us-west-2", "1.2.3.4")
    assert cmd, "subprocess.run was not called"
    remote_cmd = cmd[-1]
    assert "acp status" not in remote_cmd, (
        "Command must not contain 'acp status'; got: " + remote_cmd
    )


def test_status_ssh_command_calls_openclaw_acp():
    """Remote command should call openclaw acp."""
    cmd = _captured_ssh_cmd("claws", "us-west-2", "1.2.3.4")
    remote_cmd = cmd[-1]
    assert "openclaw acp" in remote_cmd, (
        "Remote command should contain 'openclaw acp'; got: " + remote_cmd
    )
