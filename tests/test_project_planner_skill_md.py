"""Tests for skills/project-planner/skill.md structure and content."""
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD = REPO_ROOT / "skills" / "project-planner" / "skill.md"
POLLER_LOCAL = REPO_ROOT / "openclaw" / "skills" / "github-poller" / "skill.md"
USER_DATA = REPO_ROOT / "terraform" / "user_data.sh"


def _read(path):
    return path.read_text()


def test_skill_file_exists():
    assert SKILL_MD.is_file(), f"expected skill file at {SKILL_MD}"


def test_skill_has_core_sections():
    content = _read(SKILL_MD)
    for heading in [
        "# project-planner",
        "## Step 0",
        "## Step 1",
        "## Step 2",
        "## Step 3",
        "## Step 4",
        "## Step 5",
        "## BLOCKED flow",
        "## Rules",
    ]:
        assert heading in content, f"missing section: {heading}"


def test_skill_declares_required_env_vars():
    content = _read(SKILL_MD)
    for var in [
        "CLAWS_ISSUE_NUMBER",
        "CLAWS_PROJECT_ID",
        "CLAWS_ITEM_ID",
        "CLAWS_STATUS_FIELD_ID",
        "CLAWS_STATUS_READY",
        "CLAWS_STATUS_IN_PROGRESS",
        "CLAWS_STATUS_BLOCKED",
        "CLAWS_STATUS_APPROVED",
        "GITHUB_TOKEN",
        "GITHUB_REPO",
    ]:
        assert var in content, f"skill must reference env var {var}"


def test_skill_claims_epic_via_in_progress_mutation():
    content = _read(SKILL_MD)
    assert "updateProjectV2ItemFieldValue" in content
    assert "CLAWS_STATUS_IN_PROGRESS" in content


def test_skill_uses_add_project_item_mutation():
    content = _read(SKILL_MD)
    assert "addProjectV2ItemById" in content, (
        "planner must add new child issues to the project via addProjectV2ItemById"
    )


def test_skill_creates_children_via_gh_issue_create():
    content = _read(SKILL_MD)
    assert "gh issue create" in content


def test_skill_moves_children_to_ready():
    content = _read(SKILL_MD)
    assert "CLAWS_STATUS_READY" in content


def test_skill_moves_epic_to_approved():
    content = _read(SKILL_MD)
    assert "CLAWS_STATUS_APPROVED" in content


def test_skill_states_3_to_10_constraint():
    content = _read(SKILL_MD)
    assert "3" in content and "10" in content
    assert "3 and 10" in content or "3-10" in content or "3–10" in content


def test_skill_requires_acceptance_criteria_in_children():
    content = _read(SKILL_MD)
    assert "Acceptance criteria" in content


def test_skill_forbids_recursive_epic_labelling():
    content = _read(SKILL_MD)
    lowered = content.lower()
    assert "does not recurse" in lowered or "not recurse" in lowered or "do not recurse" in lowered
    assert "epic" in lowered


def test_skill_posts_checklist_comment_on_epic():
    content = _read(SKILL_MD)
    assert "gh issue comment" in content
    assert "[ ]" in content


def test_skill_has_blocked_flow_with_mutation():
    content = _read(SKILL_MD)
    blocked_idx = content.find("## BLOCKED flow")
    assert blocked_idx != -1
    blocked = content[blocked_idx:]
    assert "CLAWS_STATUS_BLOCKED" in blocked
    assert "gh issue comment" in blocked


def test_poller_routes_epics_to_planner():
    content = _read(POLLER_LOCAL)
    assert "epic" in content.lower()
    assert "project-planner" in content
    assert "project-task" in content


def test_user_data_routes_epics_to_planner():
    content = _read(USER_DATA)
    assert "project-planner" in content
    assert "epic" in content.lower()


def test_user_data_installs_planner_skill():
    content = _read(USER_DATA)
    assert 'mkdir -p "$SKILLS_DIR/project-planner"' in content
    assert "$SKILLS_DIR/project-planner/skill.md" in content


def test_user_data_embedded_planner_has_core_sections():
    content = _read(USER_DATA)
    planner_idx = content.find("# project-planner")
    assert planner_idx != -1
    planner = content[planner_idx:]
    for heading in ["## Step 0", "## Step 3", "## Step 5", "## BLOCKED flow"]:
        assert heading in planner, f"embedded planner missing: {heading}"
