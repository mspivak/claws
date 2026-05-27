"""Tests for openclaw/skills/pr-watcher/skill.md structure and content."""
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD = REPO_ROOT / "openclaw" / "skills" / "pr-watcher" / "skill.md"


def _read_skill():
    return SKILL_MD.read_text()


def test_skill_file_exists():
    assert SKILL_MD.is_file(), f"expected skill file at {SKILL_MD}"


def test_skill_title():
    content = _read_skill()
    assert content.startswith("# pr-watcher")


def test_skill_lists_required_env_vars():
    content = _read_skill()
    for var in [
        "GITHUB_TOKEN",
        "GITHUB_REPO",
        "CLAWS_PROJECT_ID",
        "CLAWS_STATUS_FIELD_ID",
        "CLAWS_STATUS_IN_REVIEW",
        "CLAWS_STATUS_BLOCKED",
        "CLAWS_STATUS_APPROVED",
        "CLAWS_WAIT_FOR_APPROVAL",
    ]:
        assert var in content, f"skill must reference {var}"


def test_skill_documents_wait_for_approval_default_true():
    content = _read_skill()
    assert "CLAWS_WAIT_FOR_APPROVAL" in content
    assert "default" in content.lower()
    assert "true" in content.lower()


def test_skill_documents_auto_merge_label():
    content = _read_skill()
    assert "auto-merge" in content


def test_skill_documents_manual_merge_label():
    content = _read_skill()
    assert "manual-merge" in content


def test_skill_queries_in_review_cards():
    content = _read_skill()
    assert "gh api graphql" in content
    assert "CLAWS_STATUS_IN_REVIEW" in content


def test_skill_uses_squash_merge():
    content = _read_skill()
    assert "--squash" in content or "squash" in content.lower()


def test_skill_uses_gh_pr_merge():
    content = _read_skill()
    assert "gh pr merge" in content


def test_skill_checks_pr_reviews():
    content = _read_skill()
    assert "APPROVED" in content
    assert "CHANGES_REQUESTED" in content


def test_skill_checks_ci_status():
    content = _read_skill()
    assert "gh pr checks" in content or "statusCheckRollup" in content


def test_skill_handles_merge_conflict_failure():
    content = _read_skill()
    lower = content.lower()
    assert "conflict" in lower


def test_skill_moves_to_approved_after_merge_and_green_main():
    content = _read_skill()
    assert "CLAWS_STATUS_APPROVED" in content


def test_skill_moves_to_blocked_on_failure():
    content = _read_skill()
    assert "CLAWS_STATUS_BLOCKED" in content


def test_skill_deletes_branch_after_merge():
    content = _read_skill()
    assert "--delete-branch" in content or "delete-branch" in content


def test_skill_removes_worktree_after_merge():
    content = _read_skill()
    assert "worktree remove" in content


def test_skill_describes_schedule():
    content = _read_skill()
    assert "## Schedule" in content


def test_skill_waits_for_ci_on_main_after_merge():
    content = _read_skill()
    lower = content.lower()
    assert "main" in lower
    assert ("check" in lower) or ("ci" in lower)
