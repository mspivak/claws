"""Tests that pr-watcher is installed and scheduled via user_data.sh."""
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
USER_DATA = REPO_ROOT / "terraform" / "user_data.sh"


def _read_user_data():
    return USER_DATA.read_text()


def test_user_data_creates_pr_watcher_skill_dir():
    content = _read_user_data()
    assert 'mkdir -p "$SKILLS_DIR/pr-watcher"' in content


def test_user_data_writes_pr_watcher_skill_file():
    content = _read_user_data()
    assert "$SKILLS_DIR/pr-watcher/skill.md" in content


def test_user_data_registers_pr_watcher_cron():
    content = _read_user_data()
    assert "--name pr-watcher" in content


def test_user_data_pr_watcher_uses_isolated_session():
    content = _read_user_data()
    assert "pr-watcher" in content
    section = content[content.index("--name pr-watcher"):]
    section = section[: section.index("openclaw cron add") if "openclaw cron add" in section else len(section)]
    assert "--session isolated" in section
    assert "--agent claude" in section
    assert "--model claude-haiku-4-5-20251001" in section
    assert "--light-context" in section


def test_user_data_pr_watcher_runs_every_5m():
    content = _read_user_data()
    section = content[content.index("--name pr-watcher"):]
    assert "--every 5m" in section


def test_user_data_pr_watcher_reads_skill_md():
    content = _read_user_data()
    section = content[content.index("--name pr-watcher"):]
    assert "skills/pr-watcher/skill.md" in section


def test_user_data_exports_wait_for_approval_default_true():
    content = _read_user_data()
    assert "CLAWS_WAIT_FOR_APPROVAL" in content
