# pr-watcher

Runs every 5 minutes. Sweeps the GitHub project's **In Review** column and advances each card to **Approved** once its PR is merged and CI on `main` is green. Moves cards to **Blocked** on any failure mode.

Each invocation does one pass and exits.

## Environment (available via gateway — loaded from ~/.openclaw/secrets.env)

- `GITHUB_TOKEN`
- `GITHUB_REPO` (`org/repo`)
- `CLAWS_PROJECT_ID`
- `CLAWS_STATUS_FIELD_ID`
- `CLAWS_STATUS_IN_REVIEW`
- `CLAWS_STATUS_BLOCKED`
- `CLAWS_STATUS_APPROVED`
- `CLAWS_WAIT_FOR_APPROVAL` — `true` (default) or `false`
  - `true` → wait for ≥1 approving review **AND** green checks before merging
  - `false` → merge as soon as checks are green
- Per-issue label overrides:
  - `auto-merge` → behave as if `CLAWS_WAIT_FOR_APPROVAL=false` for this PR
  - `manual-merge` → skip this PR entirely (pr-watcher does nothing)

## Step 1 — Source secrets

```bash
source ~/.openclaw/secrets.env
WAIT_FOR_APPROVAL="${CLAWS_WAIT_FOR_APPROVAL:-true}"
```

## Step 2 — Fetch In Review cards

```bash
gh api graphql -f query='
  query($projectId: ID!) {
    node(id: $projectId) {
      ... on ProjectV2 {
        items(first: 50) {
          nodes {
            id
            content {
              ... on Issue { number title url repository { nameWithOwner } }
            }
            fieldValueByName(name: "Status") {
              ... on ProjectV2ItemFieldSingleSelectValue { optionId }
            }
          }
        }
      }
    }
  }
' -f projectId="$CLAWS_PROJECT_ID" \
| jq --arg s "$CLAWS_STATUS_IN_REVIEW" \
  '[.data.node.items.nodes[] | select(.fieldValueByName.optionId == $s) | select(.content.number != null)]'
```

If the list is empty, exit 0.

## Step 3 — For each In Review item

For each `(ITEM_ID, ISSUE_NUMBER)`:

### 3a — Find the PR that closes this issue

```bash
PR_JSON=$(gh pr list --repo "$GITHUB_REPO" --state open --search "linked:$ISSUE_NUMBER" --json number,headRefName,labels,reviewDecision,mergeable,mergeStateStatus,statusCheckRollup,url --limit 1)
PR_NUMBER=$(echo "$PR_JSON" | jq -r '.[0].number // empty')
```

If no open PR is linked to the issue, check whether it was already merged:

```bash
MERGED_PR=$(gh pr list --repo "$GITHUB_REPO" --state merged --search "linked:$ISSUE_NUMBER" --json number,url,mergeCommit --limit 1)
```

- If a merged PR exists → skip to **Step 4 — Post-merge handling** with that PR.
- Otherwise → skip this item (PR may still be open in draft, or issue was closed manually; leave card in In Review).

### 3b — Check labels for per-PR overrides

```bash
LABELS=$(echo "$PR_JSON" | jq -r '.[0].labels[].name')
```

- If `manual-merge` is present → skip this item.
- If `auto-merge` is present → set `EFFECTIVE_WAIT=false`.
- Otherwise → `EFFECTIVE_WAIT="$WAIT_FOR_APPROVAL"`.

### 3c — Evaluate review state

```bash
REVIEW_DECISION=$(echo "$PR_JSON" | jq -r '.[0].reviewDecision')
```

`reviewDecision` is one of `APPROVED`, `CHANGES_REQUESTED`, `REVIEW_REQUIRED`, or `null`.

- If `CHANGES_REQUESTED` → **failure**: comment on the issue with the PR URL and the changes-requested reviewer summary, then move card to **Blocked** (Step 5). Skip remaining steps for this item.
- If `EFFECTIVE_WAIT=true` and decision is not `APPROVED` → skip this item (still waiting).
- If `EFFECTIVE_WAIT=false` → proceed regardless of review decision.

### 3d — Evaluate CI on the PR

```bash
CHECK_STATE=$(echo "$PR_JSON" | jq -r '[.[0].statusCheckRollup[] | .conclusion // .status] | if any(. == "FAILURE" or . == "TIMED_OUT" or . == "CANCELLED" or . == "ACTION_REQUIRED") then "FAILED" elif any(. == "IN_PROGRESS" or . == "QUEUED" or . == "PENDING" or . == null) then "PENDING" else "SUCCESS" end')
```

- `FAILED` → **failure**: comment on the issue with the failing-checks URL (`$URL/checks`), move card to **Blocked** (Step 5). Skip remaining steps.
- `PENDING` → skip this item (try again next cron tick).
- `SUCCESS` → proceed.

### 3e — Check mergeability

```bash
MERGEABLE=$(echo "$PR_JSON" | jq -r '.[0].mergeable')
MERGE_STATE=$(echo "$PR_JSON" | jq -r '.[0].mergeStateStatus')
```

- If `MERGEABLE == "CONFLICTING"` or `MERGE_STATE == "DIRTY"` → **failure (merge conflict)**: comment on the issue noting the conflict and the PR URL, move card to **Blocked** (Step 5). Skip remaining steps.
- Otherwise → proceed.

### 3f — Squash-merge the PR

```bash
gh pr merge "$PR_NUMBER" --repo "$GITHUB_REPO" --squash --delete-branch --auto=false
```

If the merge command fails, treat as a merge conflict failure (Step 3e).

Capture the merge commit:

```bash
MERGE_COMMIT=$(gh pr view "$PR_NUMBER" --repo "$GITHUB_REPO" --json mergeCommit --jq '.mergeCommit.oid')
```

## Step 4 — Post-merge handling

Wait for CI on `main` at the merge commit to go green. Do not loop here — just check once per cron tick.

```bash
MAIN_CHECK=$(gh api "repos/$GITHUB_REPO/commits/$MERGE_COMMIT/check-runs" \
  --jq '[.check_runs[] | .conclusion // .status] | if any(. == "failure" or . == "timed_out" or . == "cancelled" or . == "action_required") then "FAILED" elif any(. == null or . == "in_progress" or . == "queued") then "PENDING" else "SUCCESS" end')
```

- `FAILED` → comment on the issue with `https://github.com/$GITHUB_REPO/commit/$MERGE_COMMIT/checks`, move card to **Blocked** (Step 5).
- `PENDING` → leave the card in In Review; the next cron tick will re-check.
- `SUCCESS` → continue.

### 4a — Move card to Approved

```bash
gh api graphql -f query='
  mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $projectId
      itemId: $itemId
      fieldId: $fieldId
      value: { singleSelectOptionId: $optionId }
    }) { projectV2Item { id } }
  }
' -f projectId="$CLAWS_PROJECT_ID" -f itemId="$ITEM_ID" -f fieldId="$CLAWS_STATUS_FIELD_ID" -f optionId="$CLAWS_STATUS_APPROVED"
```

### 4b — Clean up the local worktree

```bash
WORKTREE="$HOME/worktrees/issue-$ISSUE_NUMBER"
git -C "$HOME/repo" worktree remove --force "$WORKTREE" 2>/dev/null || true
git -C "$HOME/repo" branch -D "issue-$ISSUE_NUMBER" 2>/dev/null || true
```

## Step 5 — Blocked transition (failure helper)

```bash
gh issue comment "$ISSUE_NUMBER" --repo "$GITHUB_REPO" --body "$BODY"

gh api graphql -f query='
  mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $projectId
      itemId: $itemId
      fieldId: $fieldId
      value: { singleSelectOptionId: $optionId }
    }) { projectV2Item { id } }
  }
' -f projectId="$CLAWS_PROJECT_ID" -f itemId="$ITEM_ID" -f fieldId="$CLAWS_STATUS_FIELD_ID" -f optionId="$CLAWS_STATUS_BLOCKED"
```

Where `$BODY` describes the specific failure (changes-requested review URL, failing-checks URL on PR or main, or merge conflict on PR URL).

## Schedule

Registered as a scheduled task running every 5 minutes. This skill runs one pass per invocation and exits.

## Rules

- Never modify cards that are not in In Review.
- Never re-merge a PR that is already merged.
- A `manual-merge` label always wins — never merge those PRs.
- Failure transitions are terminal for one pass: a Blocked card will be picked back up by a human, not by this watcher.
