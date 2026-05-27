"""Tests for skills/project-task/skill.md structure and content."""
import re
from pathlib import Path

SKILL_MD = Path(__file__).parent.parent / "skills" / "project-task" / "skill.md"
POLLER_SKILL_MD = (
    Path(__file__).parent.parent / "openclaw" / "skills" / "github-poller" / "skill.md"
)


def _read_skill():
    return SKILL_MD.read_text()


def _read_poller_skill():
    return POLLER_SKILL_MD.read_text()


def _extract_step6(content):
    """Extract the content of Step 6 from the skill.md."""
    # Find Step 6 section up to the next section or end
    match = re.search(r"## Step 6.*?(?=\n## |\Z)", content, re.DOTALL)
    assert match, "Step 6 section not found in skill.md"
    return match.group(0)


def test_step6_comments_issue_before_moving_to_in_review():
    """Step 6 must post a gh issue comment BEFORE the GraphQL mutation for In Review."""
    content = _read_skill()
    step6 = _extract_step6(content)

    comment_pos = step6.find("gh issue comment")
    graphql_pos = step6.find("CLAWS_STATUS_IN_REVIEW")

    assert comment_pos != -1, (
        "Step 6 must include a 'gh issue comment' command to post the plan"
    )
    assert graphql_pos != -1, (
        "Step 6 must include the CLAWS_STATUS_IN_REVIEW mutation"
    )
    assert comment_pos < graphql_pos, (
        "The 'gh issue comment' must appear BEFORE the In Review GraphQL mutation in Step 6"
    )


def test_step6_comment_references_plan():
    """Step 6 comment must reference the plan the agent followed."""
    content = _read_skill()
    step6 = _extract_step6(content)

    assert re.search(r"[Pp]lan|[Aa]pproach|[Ii]mplementation|[Ss]ummary", step6), (
        "Step 6 comment must reference the plan or approach taken"
    )


def _extract_section(content, header_regex):
    match = re.search(rf"{header_regex}.*?(?=\n## |\Z)", content, re.DOTALL)
    assert match, f"Section matching {header_regex} not found"
    return match.group(0)


def test_resume_step_exists_between_claim_and_read():
    content = _read_skill()
    claim_pos = content.find("## Step 0 ")
    resume_pos = content.find("## Step 0.5")
    read_pos = content.find("## Step 1 ")
    assert claim_pos != -1
    assert resume_pos != -1, "Step 0.5 — Resume mode must exist"
    assert read_pos != -1
    assert claim_pos < resume_pos < read_pos, (
        "Step 0.5 must appear between Step 0 (claim) and Step 1 (read issue)"
    )


def test_resume_step_gated_on_claws_resume_env():
    content = _read_skill()
    resume = _extract_section(content, r"## Step 0\.5")
    assert "CLAWS_RESUME" in resume, (
        "Step 0.5 must check the CLAWS_RESUME environment variable"
    )


def test_resume_step_uses_last_blocked_marker():
    content = _read_skill()
    resume = _extract_section(content, r"## Step 0\.5")
    assert "CLAWS_LAST_BLOCKED_COMMENT_ID" in resume or "CLAWS_LAST_BLOCKED_AT" in resume


def test_resume_step_reblocks_when_no_new_context():
    content = _read_skill()
    resume = _extract_section(content, r"## Step 0\.5")
    assert "No new context" in resume, (
        "Resume mode must re-Block with 'No new context provided since last block'"
    )
    assert "CLAWS_STATUS_BLOCKED" in resume


def test_inputs_section_documents_resume_vars():
    content = _read_skill()
    for var in [
        "CLAWS_RESUME",
        "CLAWS_LAST_BLOCKED_COMMENT_ID",
        "CLAWS_LAST_BLOCKED_AT",
    ]:
        assert var in content, f"Inputs section must document {var}"


def test_poller_has_resume_step_before_fetch_ready():
    content = _read_poller_skill()
    resume_pos = content.find("## Step 1.5")
    fetch_pos = content.find("## Step 2 — Fetch READY items")
    assert resume_pos != -1, "github-poller skill must have Step 1.5 — resume detection"
    assert fetch_pos != -1
    assert resume_pos < fetch_pos, "Resume detection must run BEFORE fetching READY items"


def test_poller_resume_uses_existing_branch_then_origin_then_main():
    content = _read_poller_skill()
    resume_section = _extract_section(content, r"## Step 1\.5")
    assert "worktree add" in resume_section
    assert "origin/main" in resume_section, (
        "Resume worktree recovery must fall back to origin/main when branch is gone"
    )
    assert "RESUME_FRESH" in resume_section, (
        "Resume must signal a fresh-start case when branch is gone entirely"
    )


def test_poller_resume_spawns_with_claws_resume_env():
    content = _read_poller_skill()
    resume_section = _extract_section(content, r"## Step 1\.5")
    assert "CLAWS_RESUME=true" in resume_section
    assert "CLAWS_LAST_BLOCKED_COMMENT_ID" in resume_section


def test_poller_state_tracks_last_status_and_blocked_comment():
    content = _read_poller_skill()
    assert "lastStatus" in content
    assert "lastBlockedCommentId" in content
    assert "lastBlockedAt" in content


def test_poller_records_blocked_state_instead_of_removing():
    content = _read_poller_skill()
    step4 = _extract_section(content, r"## Step 4 — Monitor completed sessions")
    assert "lastBlockedCommentId" in step4, (
        "On Blocked transition, poller must record lastBlockedCommentId to enable resume"
    )
    assert "KEEP the session entry" in step4 or "keep the session" in step4.lower(), (
        "Blocked sessions must remain in poller-state.json so Step 1.5 can detect Blocked → Ready"
    )
