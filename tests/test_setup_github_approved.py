from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from claws.main import app


def _project_data_without_approved():
    return {
        "data": {
            "organization": {
                "projectV2": {
                    "id": "PVT_xyz",
                    "fields": {
                        "nodes": [
                            {
                                "id": "PVTSSF_xyz",
                                "name": "Status",
                                "options": [
                                    {"id": "opt_ready", "name": "Ready"},
                                    {"id": "opt_inprog", "name": "In Progress"},
                                    {"id": "opt_review", "name": "In Review"},
                                    {"id": "opt_blocked", "name": "Blocked"},
                                    {"id": "opt_done", "name": "Done"},
                                ],
                            }
                        ]
                    },
                }
            }
        }
    }


def _project_data_with_approved():
    return {
        "data": {
            "organization": {
                "projectV2": {
                    "id": "PVT_xyz",
                    "fields": {
                        "nodes": [
                            {
                                "id": "PVTSSF_xyz",
                                "name": "Status",
                                "options": [
                                    {"id": "opt_ready", "name": "Ready"},
                                    {"id": "opt_inprog", "name": "In Progress"},
                                    {"id": "opt_review", "name": "In Review"},
                                    {"id": "opt_blocked", "name": "Blocked"},
                                    {"id": "opt_approved", "name": "Approved"},
                                ],
                            }
                        ]
                    },
                }
            }
        }
    }


def test_setup_github_warns_and_continues_when_approved_missing():
    owner_type_data = {"data": {"repositoryOwner": {"__typename": "Organization"}}}

    call_log = []
    project_data = _project_data_without_approved()

    def fake_graphql(query, variables, env):
        if "repositoryOwner" in query:
            return owner_type_data
        return project_data

    put_calls = []

    class FakeSSM:
        def put_parameter(self, **kwargs):
            put_calls.append(kwargs)

    with (
        patch("claws.commands.setup_github._graphql", side_effect=fake_graphql),
        patch("claws.commands.setup_github.boto3") as mock_boto,
        patch("claws.commands.setup_github.subprocess.run") as mock_sub,
        patch("claws.commands.setup_github.resolve" if False else "claws.config.resolve", return_value=("myproj", "us-east-1")),
        patch("claws.commands.setup_github.Confirm.ask", return_value=False),
    ):
        mock_boto.client.return_value = FakeSSM()
        mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "setup-github",
                "--project", "myproj",
                "--token", "ghp_x",
                "--owner", "org",
                "--repo", "org/repo",
                "--project-number", "1",
                "--region", "us-east-1",
                "--yes",
            ],
        )

    assert result.exit_code == 0, result.output
    names_written = [c["Name"] for c in put_calls]
    expected = {
        "/claws/myproj/github/token",
        "/claws/myproj/github/org",
        "/claws/myproj/github/repo",
        "/claws/myproj/github/project-number",
        "/claws/myproj/github/project-id",
        "/claws/myproj/github/status-field-id",
        "/claws/myproj/github/status-ready",
        "/claws/myproj/github/status-in-progress",
        "/claws/myproj/github/status-blocked",
        "/claws/myproj/github/status-in-review",
    }
    assert expected.issubset(set(names_written))
    assert "/claws/myproj/github/status-approved" not in names_written
    assert "Approved" in result.output


def test_setup_github_writes_approved_when_present():
    owner_type_data = {"data": {"repositoryOwner": {"__typename": "Organization"}}}
    project_data = _project_data_with_approved()

    def fake_graphql(query, variables, env):
        if "repositoryOwner" in query:
            return owner_type_data
        return project_data

    put_calls = []

    class FakeSSM:
        def put_parameter(self, **kwargs):
            put_calls.append(kwargs)

    with (
        patch("claws.commands.setup_github._graphql", side_effect=fake_graphql),
        patch("claws.commands.setup_github.boto3") as mock_boto,
        patch("claws.commands.setup_github.subprocess.run") as mock_sub,
        patch("claws.config.resolve", return_value=("myproj", "us-east-1")),
    ):
        mock_boto.client.return_value = FakeSSM()
        mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "setup-github",
                "--project", "myproj",
                "--token", "ghp_x",
                "--owner", "org",
                "--repo", "org/repo",
                "--project-number", "1",
                "--region", "us-east-1",
                "--yes",
            ],
        )

    assert result.exit_code == 0, result.output
    names = [c["Name"] for c in put_calls]
    assert "/claws/myproj/github/status-approved" in names
    approved_call = next(c for c in put_calls if c["Name"] == "/claws/myproj/github/status-approved")
    assert approved_call["Value"] == "opt_approved"
