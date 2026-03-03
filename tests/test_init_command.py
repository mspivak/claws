"""Tests for the claws init command."""
import inspect
import typer
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

from claws.main import app
from claws.commands import init

runner = CliRunner()


def test_default_instance_type_is_smallest():
    """The default EC2 instance type should be t3.nano (smallest general-purpose)."""
    sig = inspect.signature(init.run)
    default = sig.parameters["instance_type"].default
    # Extract default value from typer.Option
    assert default.default == "t3.nano", (
        f"Expected default instance type 't3.nano', got '{default.default}'"
    )


def test_custom_instance_type_is_passed_to_terraform():
    """Custom instance type should be forwarded to terraform as a -var argument."""
    with (
        patch("claws.commands.init._check_aws_credentials"),
        patch("claws.commands.init._run") as mock_run,
        patch("subprocess.run") as mock_subprocess,
        patch("claws.commands.init.save_project_config"),
    ):
        mock_subprocess.return_value = MagicMock(returncode=1)
        result = runner.invoke(
            app,
            [
                "init",
                "--project", "test-project",
                "--repo", "org/repo",
                "--region", "us-east-1",
                "--instance-type", "t3.medium",
            ],
        )
        # Find the apply call
        apply_call = next(
            (call for call in mock_run.call_args_list if "apply" in call.args[0]),
            None,
        )
        assert apply_call is not None
        assert "-var=instance_type=t3.medium" in apply_call.args[0]
