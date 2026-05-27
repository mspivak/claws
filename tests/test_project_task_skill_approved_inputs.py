"""Tests that project-task skill preamble references the post-In-Review handoff."""
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD = REPO_ROOT / "skills" / "project-task" / "skill.md"


def _read_skill():
    return SKILL_MD.read_text()


def test_inputs_mention_status_approved():
    content = _read_skill()
    assert "CLAWS_STATUS_APPROVED" in content


def test_preamble_mentions_separate_watcher():
    content = _read_skill()
    lower = content.lower()
    assert "pr-watcher" in lower or "watcher" in lower
