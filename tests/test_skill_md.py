"""Tests for skills/project-task/skill.md structure and content."""
import re
from pathlib import Path

SKILL_MD = Path(__file__).parent.parent / "skills" / "project-task" / "skill.md"


def _read_skill():
    return SKILL_MD.read_text()


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

    # The comment body should mention the plan or approach
    assert re.search(r"[Pp]lan|[Aa]pproach|[Ii]mplementation|[Ss]ummary", step6), (
        "Step 6 comment must reference the plan or approach taken"
    )
