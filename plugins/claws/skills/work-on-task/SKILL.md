---
name: work-on-task
description: Autonomous, non-interactive agent that takes a single GitHub issue from Ready to In Review in a dedicated git worktree (plan, TDD, open a PR). Dispatched by work-on-pending; can also be run directly with the CLAWS_* env inputs set. Never asks questions — signals Blocked via GitHub and exits.
disable-model-invocation: true
---

# work-on-task

You are a non-interactive autonomous agent working on a GitHub issue in a dedicated git worktree.
You must never ask the user questions. If you are blocked, signal it via GitHub and exit.

## Inputs (environment variables set by the poller)

- `CLAWS_ISSUE_NUMBER` — GitHub issue number to work on
- `CLAWS_PROJECT_ID` — GraphQL project ID (PVT_...)
- `CLAWS_ITEM_ID` — GraphQL project item ID for this issue
- `CLAWS_STATUS_FIELD_ID` — GraphQL status field ID
- `CLAWS_STATUS_IN_PROGRESS` — option ID for "In Progress"
- `CLAWS_STATUS_BLOCKED` — option ID for "Blocked"
- `CLAWS_STATUS_IN_REVIEW` — option ID for "In Review"
- `CLAWS_STATUS_APPROVED` — option ID for "Approved" (not used by this skill; consumed by the `pr-watcher` skill that advances cards from In Review → Approved)
- `GITHUB_TOKEN` — GitHub PAT
- `GITHUB_REPO` — org/repo
- `CLAWS_RESUME` — optional. When set to `true`, run Step 0.5 — Resume mode before Step 1.
- `CLAWS_LAST_BLOCKED_COMMENT_ID` — optional. GraphQL node ID of the comment that accompanied the last BLOCKED transition. Used to find comments newer than the block.
- `CLAWS_LAST_BLOCKED_AT` — optional. ISO8601 timestamp of the last BLOCKED transition (fallback when `CLAWS_LAST_BLOCKED_COMMENT_ID` is unavailable).

## Scope

This skill drives a task from **Ready → In Progress → In Review** (or Blocked).
A separate `pr-watcher` skill (`openclaw/skills/pr-watcher/skill.md`) sweeps the In Review column on a cron and advances each card to **Approved** once its PR is merged and CI on `main` is green. Do not attempt to merge the PR or move the card past In Review from this skill — exit as soon as the In Review transition succeeds.

## Step 0 — Claim the task

Move the issue to "In Progress" atomically. If this fails, someone else claimed it — exit immediately.

```bash
gh api graphql -f query='
  mutation {
    updateProjectV2ItemFieldValue(input: {
      projectId: "$CLAWS_PROJECT_ID"
      itemId: "$CLAWS_ITEM_ID"
      fieldId: "$CLAWS_STATUS_FIELD_ID"
      value: { singleSelectOptionId: "$CLAWS_STATUS_IN_PROGRESS" }
    }) { projectV2Item { id } }
  }
'
```

If the mutation returns an error, exit 0 immediately.

## Step 0.5 — Resume mode

Skip this step entirely when `CLAWS_RESUME` is not `true`.

When `CLAWS_RESUME=true`, the issue was previously Blocked and a human has moved it back to Ready. Before re-planning, read every comment newer than the BLOCKED comment so the new context is in the working set.

```bash
gh issue view $CLAWS_ISSUE_NUMBER --repo $GITHUB_REPO --json comments \
  | jq --arg since "$CLAWS_LAST_BLOCKED_AT" --arg lastId "$CLAWS_LAST_BLOCKED_COMMENT_ID" '
      [ .comments[]
        | select(
            ($lastId != "" and .id != $lastId and (.createdAt >= $since))
            or ($lastId == "" and ($since == "" or .createdAt > $since))
          )
      ]
    '
```

If `CLAWS_LAST_BLOCKED_COMMENT_ID` is set, treat that as the boundary: any comment with `createdAt >= CLAWS_LAST_BLOCKED_AT` and a different node ID is "new context". If neither is set, fall back to "every comment posted after the most recent comment authored by the agent itself".

If the result is empty, the human moved the card back without adding context. Re-Block immediately and exit:

```bash
gh issue comment $CLAWS_ISSUE_NUMBER \
  --repo $GITHUB_REPO \
  --body "**Blocked**: No new context provided since last block.

**To unblock**: Add a comment explaining what changed before moving the card back to Ready."

gh api graphql -f query='
  mutation {
    updateProjectV2ItemFieldValue(input: {
      projectId: "$CLAWS_PROJECT_ID"
      itemId: "$CLAWS_ITEM_ID"
      fieldId: "$CLAWS_STATUS_FIELD_ID"
      value: { singleSelectOptionId: "$CLAWS_STATUS_BLOCKED" }
    }) { projectV2Item { id } }
  }
'
```

Exit 0.

Otherwise, read each new comment carefully and treat its content as authoritative additions to the issue body for the rest of this run. Then proceed to Step 1.

When in resume mode, the worktree may already contain prior commits from the previous session — inspect `git log origin/main..HEAD` before re-planning. The aim is to advance from where the prior session stopped, not redo it.

## Step 1 — Read the issue

```bash
gh issue view $CLAWS_ISSUE_NUMBER --repo $GITHUB_REPO --json title,body,labels,comments
```

Read the full issue body and all comments carefully. Understand what needs to be done.

## Step 2 — Plan

Before writing any code, think through:
- What files need to change?
- What is the minimal change needed?
- Are there any ambiguities?

If there is any ambiguity that would prevent you from completing the task, go to the BLOCKED flow below.

## Step 3 — TDD: write failing tests first

Write tests that describe the expected behavior. Run them and confirm they fail.

## Step 4 — Implement

Make the minimal code change to pass the tests. Run tests again and confirm they pass.

## Step 5 — Create PR

```bash
git add -A
git commit -m "<concise description of change>"
git push origin HEAD
```

If a PR already exists for this branch (resume case), skip `gh pr create` — the push above is enough. Detect with:

```bash
EXISTING_PR=$(gh pr list --repo $GITHUB_REPO --head "$(git branch --show-current)" --json number -q '.[0].number')
if [ -z "$EXISTING_PR" ]; then
  gh pr create \
    --repo $GITHUB_REPO \
    --title "<issue title>" \
    --body "Closes #$CLAWS_ISSUE_NUMBER" \
    --base main
fi
```

## Step 6 — Move to In Review

Post a comment on the issue summarising the plan you followed and what was implemented:

```bash
gh issue comment $CLAWS_ISSUE_NUMBER \
  --repo $GITHUB_REPO \
  --body "## Implementation Plan

**Approach**: <one-sentence summary of the approach taken>

**Changes made**:
- <file or component changed>: <what was done>

**Tests**: <brief description of tests written and what they verify>"
```

Then move the card to In Review:

```bash
gh api graphql -f query='
  mutation {
    updateProjectV2ItemFieldValue(input: {
      projectId: "$CLAWS_PROJECT_ID"
      itemId: "$CLAWS_ITEM_ID"
      fieldId: "$CLAWS_STATUS_FIELD_ID"
      value: { singleSelectOptionId: "$CLAWS_STATUS_IN_REVIEW" }
    }) { projectV2Item { id } }
  }
'
```

Exit 0.

---

## BLOCKED flow

Use this whenever you cannot complete the task without human input.

```bash
gh issue comment $CLAWS_ISSUE_NUMBER \
  --repo $GITHUB_REPO \
  --body "**Blocked**: <clear explanation of what is unclear or missing>

**To unblock**: <specific action the human must take>"

gh api graphql -f query='
  mutation {
    updateProjectV2ItemFieldValue(input: {
      projectId: "$CLAWS_PROJECT_ID"
      itemId: "$CLAWS_ITEM_ID"
      fieldId: "$CLAWS_STATUS_FIELD_ID"
      value: { singleSelectOptionId: "$CLAWS_STATUS_BLOCKED" }
    }) { projectV2Item { id } }
  }
'
```

Exit 0.

---

## Rules

- Never use `AskUserQuestion` or any interactive tool
- Never ask for confirmation — either proceed or signal blocked
- Work only in the current directory (the worktree)
- Never commit directly to main
- Keep commits focused and atomic
- If tests don't exist for the area you're modifying, write them first
