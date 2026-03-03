"""Tests for .claws/project.json config loading/saving and command integration."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from claws.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# config module unit tests
# ---------------------------------------------------------------------------


def test_load_returns_empty_when_no_config(tmp_path, monkeypatch):
    """load_project_config returns {} when no .claws/project.json exists."""
    monkeypatch.chdir(tmp_path)
    from claws import config
    assert config.load_project_config() == {}


def test_load_reads_project_and_region(tmp_path, monkeypatch):
    """load_project_config reads project and region from .claws/project.json."""
    config_dir = tmp_path / ".claws"
    config_dir.mkdir()
    (config_dir / "project.json").write_text(
        json.dumps({"project": "my-proj", "region": "eu-west-1"})
    )
    monkeypatch.chdir(tmp_path)
    from claws import config
    cfg = config.load_project_config()
    assert cfg["project"] == "my-proj"
    assert cfg["region"] == "eu-west-1"


def test_load_walks_up_to_find_config(tmp_path, monkeypatch):
    """load_project_config walks up directory tree to find .claws/project.json."""
    config_dir = tmp_path / ".claws"
    config_dir.mkdir()
    (config_dir / "project.json").write_text(
        json.dumps({"project": "parent-proj", "region": "ap-southeast-1"})
    )
    subdir = tmp_path / "sub" / "nested"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    from claws import config
    cfg = config.load_project_config()
    assert cfg["project"] == "parent-proj"


def test_save_creates_claws_directory_and_file(tmp_path):
    """save_project_config creates .claws/project.json with project and region."""
    from claws import config
    path = config.save_project_config("test-proj", "us-east-1", directory=tmp_path)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["project"] == "test-proj"
    assert data["region"] == "us-east-1"


def test_save_returns_path_to_config_file(tmp_path):
    """save_project_config returns the path to the written file."""
    from claws import config
    path = config.save_project_config("proj", "us-west-2", directory=tmp_path)
    assert path == tmp_path / ".claws" / "project.json"


def test_resolve_uses_flags_when_provided():
    """resolve() returns the explicit flag values unchanged."""
    from claws import config
    project, region = config.resolve("my-project", "us-east-1", {})
    assert project == "my-project"
    assert region == "us-east-1"


def test_resolve_falls_back_to_config():
    """resolve() fills in missing values from the config dict."""
    from claws import config
    project, region = config.resolve(None, None, {"project": "cfg-proj", "region": "cfg-region"})
    assert project == "cfg-proj"
    assert region == "cfg-region"


def test_resolve_raises_when_project_missing():
    """resolve() raises ValueError when project cannot be determined."""
    from claws import config
    with pytest.raises(ValueError, match="project"):
        config.resolve(None, "us-east-1", {})


def test_resolve_raises_when_region_missing():
    """resolve() raises ValueError when region cannot be determined."""
    from claws import config
    with pytest.raises(ValueError, match="region"):
        config.resolve("my-project", None, {})


# ---------------------------------------------------------------------------
# Integration: status command picks up config file
# ---------------------------------------------------------------------------


def test_status_uses_config_file_when_no_flags(tmp_path, monkeypatch):
    """status command reads project/region from .claws/project.json when omitted."""
    config_dir = tmp_path / ".claws"
    config_dir.mkdir()
    (config_dir / "project.json").write_text(
        json.dumps({"project": "cfg-project", "region": "us-west-2"})
    )
    monkeypatch.chdir(tmp_path)

    from claws.commands import status

    with (
        patch.object(status, "_get_instance", return_value=None),
    ):
        result = runner.invoke(app, ["status"])

    # Should not fail with "Missing option '--project'" - it reads from config
    assert "Missing option '--project'" not in result.output
    assert "Missing option '--region'" not in result.output


def test_status_fails_helpfully_without_flags_or_config(tmp_path, monkeypatch):
    """status without flags or config exits with a helpful message."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["status"])
    assert result.exit_code != 0
    output = result.output.lower()
    assert "project" in output or "project.json" in output


# ---------------------------------------------------------------------------
# Integration: init command writes config file
# ---------------------------------------------------------------------------


def test_init_writes_project_config_after_apply(tmp_path, monkeypatch):
    """init command writes .claws/project.json after successful terraform apply."""
    monkeypatch.chdir(tmp_path)

    from claws.commands import init

    with (
        patch("claws.commands.init._check_aws_credentials"),
        patch("claws.commands.init._run"),
        patch("subprocess.run") as mock_subprocess,
    ):
        mock_subprocess.return_value = MagicMock(returncode=1)  # ssh command fails, that's ok
        result = runner.invoke(
            app,
            [
                "init",
                "--project", "written-proj",
                "--repo", "org/repo",
                "--region", "eu-central-1",
            ],
        )

    config_path = tmp_path / ".claws" / "project.json"
    assert config_path.exists(), f"Expected .claws/project.json to be created; exit={result.exit_code} output={result.output}"
    data = json.loads(config_path.read_text())
    assert data["project"] == "written-proj"
    assert data["region"] == "eu-central-1"
