---
name: work-on-pending
description: Run one pass over a GitHub Project's Ready column and dispatch an autonomous subagent for each pending card (up to maxConcurrent). Use when the user wants to pick up / work on pending GitHub Project tasks locally, drive the claws dogfooding workflow from Claude Code, or runs /work-on-pending (optionally wrapped in /loop). Reads config from .claws.json or CLAWS_* env vars.
argument-hint: "[projectNumber=N] [maxConcurrent=N]"
---

# work-on-pending

Local counterpart to the OpenClaw `github-poller`. One invocation = one pass over the project's Ready issues, dispatching a `work-on-task` subagent for each one (up to `maxConcurrent`).

Designed to be triggered from Claude Code on the operator's laptop, optionally wrapped in `/loop 5m /work-on-pending` for a periodic re-poll within a long-running session.

## Inputs

Resolved in this order (first non-empty wins):

1. Skill args passed inline (e.g. `projectNumber=1 maxConcurrent=2`)
2. `.claws.json` at the repo root
3. Environment variables: `CLAWS_PROJECT_URL`, `CLAWS_PROJECT_NUMBER`, `CLAWS_OWNER`, `CLAWS_MAX_CONCURRENT`, `CLAWS_WORKTREE_PARENT`

`.claws.json` shape:

```json
{
  "projectUrl": "https://github.com/users/mspivak/projects/1",
  "projectNumber": 1,
  "owner": "mspivak",
  "maxConcurrent": 1,
  "worktreeParent": ".."
}
```

`maxConcurrent` defaults to `1`. `worktreeParent` defaults to `..` (sibling directory).

## Prerequisites

- `gh` CLI authenticated locally (`gh auth status` must succeed). No SSM, no PAT injection.
- The repo is a clean git checkout — the skill creates worktrees off `origin/main`.
- Run from the repo root.

## Step 1 — Load config

Read `.claws.json` from the current working directory. If missing, fall back to env vars. If neither yields a `projectNumber` and `owner`, exit with a clear error pointing the user at `.claws.example.json`.

Resolve `GITHUB_REPO` from `gh repo view --json nameWithOwner -q .nameWithOwner`.

## Step 2 — Discover project metadata

The poller needs the same IDs the `work-on-task` skill consumes. Fetch them via GraphQL using local `gh` auth:

```bash
gh api graphql -f query='
  query($owner: String!, $number: Int!) {
    user(login: $owner) {
      projectV2(number: $number) {
        id
        field(name: "Status") {
          ... on ProjectV2SingleSelectField {
            id
            options { id name }
          }
        }
      }
    }
  }
' -f owner="$OWNER" -F number="$PROJECT_NUMBER"
```

If the project belongs to an organisation instead of a user, swap `user(login:...)` for `organization(login:...)`. Detect this from `projectUrl` (`/users/` vs `/orgs/`); if `projectUrl` is missing, try `user` first then `organization`.

Extract:
- `projectId`
- `statusFieldId`
- Option IDs for `Ready`, `In Progress`, `In Review`, `Blocked` (match by `name`, case-insensitive)

If any option is missing, print which one and exit.

## Step 3 — List Ready cards

```bash
gh api graphql -f query='
  query($projectId: ID!) {
    node(id: $projectId) {
      ... on ProjectV2 {
        items(first: 50) {
          nodes {
            id
            content { ... on Issue { number title url } }
            fieldValueByName(name: "Status") {
              ... on ProjectV2ItemFieldSingleSelectValue { optionId }
            }
          }
        }
      }
    }
  }
' -f projectId="$PROJECT_ID" \
| jq --arg ready "$STATUS_READY" '
    [.data.node.items.nodes[]
     | select(.fieldValueByName.optionId == $ready)
     | select(.content.number != null)]
  '
```

## Step 4 — Filter in-flight issues

Read `.claws/state.json` if it exists (initialize to `{"inflight": []}` otherwise). Drop any Ready card whose issue number appears in `inflight`. This protects against re-dispatching when `/loop` fires another pass before a subagent finishes.

`.claws/` is gitignored.

## Step 5 — Dispatch up to `maxConcurrent`

Take the first `maxConcurrent` filtered cards. For each one, serially:

### 5a — Claim atomically

Move the card to In Progress with the same mutation the `work-on-task` skill uses:

```bash
gh api graphql -f query='
  mutation {
    updateProjectV2ItemFieldValue(input: {
      projectId: "'"$PROJECT_ID"'"
      itemId: "'"$ITEM_ID"'"
      fieldId: "'"$STATUS_FIELD_ID"'"
      value: { singleSelectOptionId: "'"$STATUS_IN_PROGRESS"'" }
    }) { projectV2Item { id } }
  }
'
```

If the mutation errors (someone else claimed it), skip this card and continue.

### 5b — Create the worktree

```bash
REPO_NAME=$(basename "$(git rev-parse --show-toplevel)")
WORKTREE="$WORKTREE_PARENT/${REPO_NAME}-issue-${ISSUE_NUMBER}"
git fetch origin main
git worktree add "$WORKTREE" -b "issue-${ISSUE_NUMBER}" origin/main 2>/dev/null \
  || git worktree add "$WORKTREE" "issue-${ISSUE_NUMBER}"
```

The worktree must live at `<worktreeParent>/<repo>-issue-N` (sibling by default, never inside the repo).

### 5c — Record in-flight

Append `ISSUE_NUMBER` to `.claws/state.json` `inflight` list before spawning the subagent so a concurrent re-poll won't re-dispatch.

### 5d — Spawn the subagent

Use Claude Code's `Agent` tool with `subagent_type: "general-purpose"`. Pass the full contents of `${CLAUDE_PLUGIN_ROOT}/skills/work-on-task/SKILL.md` plus the env-equivalent values inline in the prompt. The subagent runs in-process — no ACP, no SSM.

Prompt template:

```
You are an autonomous engineer working on GitHub issue #<ISSUE_NUMBER> in repo <GITHUB_REPO>.

WORKING DIRECTORY: <WORKTREE>
Run ALL commands from there — prefix shell calls with `cd <WORKTREE> && ...`. Your branch `issue-<ISSUE_NUMBER>` is already checked out.

Follow the skill below exactly. Treat the variables in the "Inputs" section as if they were environment variables with these values:

CLAWS_ISSUE_NUMBER=<ISSUE_NUMBER>
CLAWS_PROJECT_ID=<PROJECT_ID>
CLAWS_ITEM_ID=<ITEM_ID>
CLAWS_STATUS_FIELD_ID=<STATUS_FIELD_ID>
CLAWS_STATUS_IN_PROGRESS=<STATUS_IN_PROGRESS>
CLAWS_STATUS_BLOCKED=<STATUS_BLOCKED>
CLAWS_STATUS_IN_REVIEW=<STATUS_IN_REVIEW>
GITHUB_REPO=<GITHUB_REPO>

The card has already been moved to In Progress for you — skip Step 0's mutation and go straight to Step 1.

--- BEGIN work-on-task skill ---
<full contents of ${CLAUDE_PLUGIN_ROOT}/skills/work-on-task/SKILL.md>
--- END work-on-task skill ---

When you finish (PR opened and card moved to In Review, OR card moved to Blocked), report:
  Issue: #<ISSUE_NUMBER>
  Final state: In Review | Blocked | Errored
  PR URL: <url or N/A>
  One-line summary of what was done.
```

After the `Agent` call returns, remove `ISSUE_NUMBER` from `.claws/state.json`'s `inflight` list and record the subagent's reported outcome.

## Step 6 — Print summary

After all dispatched subagents return, print a compact table:

```
Dispatched 2 issue(s):

  #42  In Review  https://github.com/mspivak/claws/pull/57   "Add foo to bar"
  #44  Blocked    —                                          "Refactor baz"
```

If no Ready cards were available, print `No Ready cards.` and exit.

## Rules

- Never push to `main` directly from this skill — only the subagent pushes, and only to `issue-N`.
- Never delete the worktree from this skill. Leave cleanup to the operator (or a separate skill) so the user can inspect failures.
- If `gh auth status` fails, exit with a clear message — do not try to recover.
- Serial dispatch only. Parallel `Agent` calls are technically possible but out of scope for this skill (the issue body calls this out).
