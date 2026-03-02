# github-poller

Runs every 60 seconds. Polls the GitHub project for READY tasks and spawns Claude Code ACP sessions to work on them.

## Environment (loaded from ~/.openclaw/secrets.env)

- `GITHUB_TOKEN`
- `GITHUB_ORG`
- `GITHUB_REPO`
- `CLAWS_PROJECT_ID`
- `CLAWS_STATUS_FIELD_ID`
- `CLAWS_STATUS_READY`
- `CLAWS_STATUS_IN_PROGRESS`
- `CLAWS_STATUS_BLOCKED`
- `CLAWS_STATUS_IN_REVIEW`

## Step 1 — Check active session count

```bash
ACTIVE=$(openclaw acp list --json | jq '[.[] | select(.status == "running")] | length')
MAX=4
AVAILABLE=$((MAX - ACTIVE))
```

If `AVAILABLE == 0`, exit — nothing to do.

## Step 2 — Fetch READY items

```bash
gh api graphql -f query='
  query($projectId: ID!, $statusFieldId: ID!, $readyOptionId: String!) {
    node(id: $projectId) {
      ... on ProjectV2 {
        items(first: 20) {
          nodes {
            id
            content {
              ... on Issue {
                number
                title
                url
              }
            }
            fieldValueByName(name: "Status") {
              ... on ProjectV2ItemFieldSingleSelectValue {
                optionId
              }
            }
          }
        }
      }
    }
  }
' \
-f projectId="$CLAWS_PROJECT_ID" \
-f statusFieldId="$CLAWS_STATUS_FIELD_ID" \
-f readyOptionId="$CLAWS_STATUS_READY" \
| jq '[.data.node.items.nodes[] | select(.fieldValueByName.optionId == env.CLAWS_STATUS_READY) | select(.content.number != null)]'
```

Take up to `$AVAILABLE` items from this list.

## Step 3 — For each READY item

For each item (using `ITEM_ID`, `ISSUE_NUMBER`):

### 3a — Create a worktree

```bash
WORKTREE="$HOME/worktrees/issue-$ISSUE_NUMBER"
git -C "$HOME/repo" worktree add "$WORKTREE" main
```

### 3b — Spawn an ACP session

```bash
openclaw acp spawn claude \
  --cwd "$WORKTREE" \
  --skill project-task \
  --env CLAWS_ISSUE_NUMBER="$ISSUE_NUMBER" \
  --env CLAWS_PROJECT_ID="$CLAWS_PROJECT_ID" \
  --env CLAWS_ITEM_ID="$ITEM_ID" \
  --env CLAWS_STATUS_FIELD_ID="$CLAWS_STATUS_FIELD_ID" \
  --env CLAWS_STATUS_IN_PROGRESS="$CLAWS_STATUS_IN_PROGRESS" \
  --env CLAWS_STATUS_BLOCKED="$CLAWS_STATUS_BLOCKED" \
  --env CLAWS_STATUS_IN_REVIEW="$CLAWS_STATUS_IN_REVIEW" \
  --env GITHUB_TOKEN="$GITHUB_TOKEN" \
  --env GITHUB_REPO="$GITHUB_REPO"
```

Record the session ID → issue number mapping in `~/.openclaw/poller-state.json`.

## Step 4 — Monitor completed sessions

Check for sessions that finished since last poll:

```bash
openclaw acp list --json | jq '[.[] | select(.status == "done" or .status == "error")]'
```

For each finished session:
1. Look up the issue number from `~/.openclaw/poller-state.json`
2. Check the issue's current status in the GitHub project
3. If status is "Blocked":
   - Read the latest blocking comment from the issue
   - Send Telegram notification: `⚠️ Issue #N is blocked\n<comment body>\n<issue URL>`
4. If status is "In Review" or the session exited cleanly:
   - Clean up the worktree: `git -C "$HOME/repo" worktree remove --force "$WORKTREE"`
5. Remove the session from `~/.openclaw/poller-state.json`

## Telegram notification format

```
⚠️ *Issue #N blocked*: <title>

<blocking comment>

<issue URL>
```

Send via:
```bash
openclaw notify telegram "⚠️ *Issue #$ISSUE_NUMBER blocked*: $TITLE\n\n$COMMENT\n\n$URL"
```

## State file format (`~/.openclaw/poller-state.json`)

```json
{
  "sessions": {
    "<session-id>": {
      "issueNumber": 42,
      "itemId": "PVTI_...",
      "worktree": "/home/ec2-user/worktrees/issue-42"
    }
  }
}
```

Initialize to `{"sessions": {}}` if file doesn't exist.

## Schedule

This skill is registered as a scheduled task running every 60 seconds.
OpenClaw handles the scheduling — this skill just runs once per invocation and exits.
