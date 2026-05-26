"""Tests for skills/poll-project/skill.md structure and content."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD = REPO_ROOT / "skills" / "poll-project" / "skill.md"
EXAMPLE_CONFIG = REPO_ROOT / ".claws.example.json"
GITIGNORE = REPO_ROOT / ".gitignore"
README = REPO_ROOT / "README.md"


def _read_skill():
    return SKILL_MD.read_text()


def test_skill_file_exists():
    assert SKILL_MD.is_file(), f"expected skill file at {SKILL_MD}"


def test_skill_has_core_sections():
    content = _read_skill()
    for heading in [
        "# poll-project",
        "## Step 1",
        "## Step 2",
        "## Step 3",
        "## Step 4",
        "## Step 5",
        "## Step 6",
    ]:
        assert heading in content, f"missing section: {heading}"


def test_skill_references_claws_json_config():
    content = _read_skill()
    assert ".claws.json" in content
    assert "projectNumber" in content
    assert "maxConcurrent" in content
    assert "worktreeParent" in content


def test_skill_uses_local_gh_no_ssm():
    content = _read_skill()
    assert "gh api graphql" in content
    assert "SSM" not in content or "no SSM" in content.lower() or "No SSM" in content


def test_skill_claims_via_in_progress_mutation():
    content = _read_skill()
    assert "updateProjectV2ItemFieldValue" in content
    assert "STATUS_IN_PROGRESS" in content


def test_skill_creates_worktree_at_sibling_path():
    content = _read_skill()
    assert "git worktree add" in content
    assert "issue-${ISSUE_NUMBER}" in content or "issue-$ISSUE_NUMBER" in content


def test_skill_spawns_agent_subagent():
    content = _read_skill()
    assert "Agent" in content
    assert "general-purpose" in content
    assert "project-task" in content


def test_skill_passes_env_equivalents_to_subagent():
    content = _read_skill()
    for var in [
        "CLAWS_ISSUE_NUMBER",
        "CLAWS_PROJECT_ID",
        "CLAWS_ITEM_ID",
        "CLAWS_STATUS_FIELD_ID",
        "CLAWS_STATUS_IN_PROGRESS",
        "CLAWS_STATUS_BLOCKED",
        "CLAWS_STATUS_IN_REVIEW",
        "GITHUB_REPO",
    ]:
        assert var in content, f"subagent prompt must mention {var}"


def test_example_config_is_valid_json_with_expected_keys():
    assert EXAMPLE_CONFIG.is_file()
    data = json.loads(EXAMPLE_CONFIG.read_text())
    for key in ["projectNumber", "owner", "maxConcurrent", "worktreeParent"]:
        assert key in data, f".claws.example.json missing key: {key}"


def test_gitignore_excludes_claws_dir():
    content = GITIGNORE.read_text()
    assert ".claws/" in content


def test_readme_has_run_from_laptop_section():
    content = README.read_text()
    assert "Run from your laptop" in content
    assert "poll-project" in content
