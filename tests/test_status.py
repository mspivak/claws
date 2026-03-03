from unittest.mock import MagicMock, patch


def _all_ssh_remote_cmds(project, region, ip):
    """Run status.run() and return all remote commands sent via SSH."""
    from claws.commands import status

    all_cmds = []

    def fake_subprocess_run(cmd, **kwargs):
        all_cmds.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        return result

    fake_instance = {"PublicIpAddress": ip, "InstanceId": "i-test"}

    with (
        patch.object(status, "_get_instance", return_value=fake_instance),
        patch("claws.commands.status.subprocess.run", side_effect=fake_subprocess_run),
        patch("claws.commands.status.boto3"),
    ):
        from typer.testing import CliRunner
        from claws.main import app

        runner = CliRunner()
        runner.invoke(app, ["status", "--project", project, "--region", region])

    # Return only the remote command part (last element) from each SSH call
    return [cmd[-1] for cmd in all_cmds if isinstance(cmd, list) and len(cmd) > 0]


def test_status_ssh_command_does_not_pass_status_argument():
    """openclaw acp must not receive 'status' as an argument."""
    cmds = _all_ssh_remote_cmds("claws", "us-west-2", "1.2.3.4")
    assert cmds, "subprocess.run was not called"
    for remote_cmd in cmds:
        assert "acp status" not in remote_cmd, (
            "Command must not contain 'acp status'; got: " + remote_cmd
        )


def test_status_ssh_fetches_sessions_list():
    """status command must fetch sessions via openclaw gateway call sessions.list."""
    cmds = _all_ssh_remote_cmds("claws", "us-west-2", "1.2.3.4")
    assert any("sessions.list" in c for c in cmds), (
        "Expected an SSH call containing 'sessions.list'; got: " + str(cmds)
    )
