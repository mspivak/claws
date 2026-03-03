# github-poller

Runs every 60 seconds. Polls the GitHub project for READY tasks and spawns Claude Code ACP sessions to work on them.

## Environment (available via gateway — loaded from ~/.openclaw/secrets.env)

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

Use the `sessions_list` tool with `{"kinds": ["acp"], "activeMinutes": 120}`.

Count running sessions. MAX=4. If `MAX - active == 0`, exit — nothing to do.

Also read `~/.openclaw/poller-state.json` (initialize to `{"sessions":{}}` if missing).

## Step 2 — Fetch READY items

```bash
source ~/.openclaw/secrets.env
gh api graphql -f query='
  query($projectId: ID!) {
    node(id: $projectId) {
      ... on ProjectV2 {
        items(first: 20) {
          nodes {
            id
            content {
              ... on Issue { number title url }
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
| jq --arg ready "$CLAWS_STATUS_READY" \
  '[.data.node.items.nodes[] | select(.fieldValueByName.optionId == $ready) | select(.content.number != null)]'
```

Take up to `AVAILABLE` items from this list. Skip any issue already tracked in `poller-state.json`.

## Step 3 — For each READY item

For each item (`ITEM_ID`, `ISSUE_NUMBER`):

### 3a — Create a worktree

```bash
source ~/.openclaw/secrets.env
WORKTREE="$HOME/worktrees/issue-$ISSUE_NUMBER"
git -C "$HOME/repo" worktree add "$WORKTREE" -b "issue-$ISSUE_NUMBER" origin/main 2>/dev/null \
  || git -C "$HOME/repo" worktree add "$WORKTREE" "issue-$ISSUE_NUMBER" 2>/dev/null \
  || true
```

### 3b — Spawn an ACP session

Use the `sessions_spawn` tool:

```json
{
  "runtime": "acp",
  "agentId": "claude",
  "mode": "oneshot",
  "label": "poller-issue-<ISSUE_NUMBER>",
  "cwd": "/home/ec2-user/worktrees/issue-<ISSUE_NUMBER>",
  "task": "Read ~/.openclaw/skills/project-task/skill.md and follow it exactly.\n\nEnvironment:\nCLAWS_ISSUE_NUMBER=<ISSUE_NUMBER>\nCLAWS_PROJECT_ID=<CLAWS_PROJECT_ID>\nCLAWS_ITEM_ID=<ITEM_ID>\nCLAWS_STATUS_FIELD_ID=<CLAWS_STATUS_FIELD_ID>\nCLAWS_STATUS_IN_PROGRESS=<CLAWS_STATUS_IN_PROGRESS>\nCLAWS_STATUS_BLOCKED=<CLAWS_STATUS_BLOCKED>\nCLAWS_STATUS_IN_REVIEW=<CLAWS_STATUS_IN_REVIEW>\nGITHUB_REPO=<GITHUB_REPO>"
}
```

Record the returned session key → issue mapping in `~/.openclaw/poller-state.json`:

```json
{
  "sessions": {
    "<session-key>": {
      "issueNumber": 42,
      "itemId": "PVTI_...",
      "worktree": "/home/ec2-user/worktrees/issue-42",
      "label": "poller-issue-42"
    }
  }
}
```

## Step 4 — Monitor completed sessions

Use `sessions_list` with `{"kinds": ["acp"], "activeMinutes": 120}` to get currently active sessions.

For each session tracked in `poller-state.json` that is no longer in the active list:

1. Look up the issue number from `poller-state.json`
2. Check the issue's current status in the GitHub project via GraphQL
3. If status is "Blocked":
   - Read the latest comment from the issue
   - Send Telegram notification:
     ```bash
     openclaw notify telegram "⚠️ *Issue #$ISSUE_NUMBER blocked*: $TITLE\n\n$COMMENT\n\n$URL"
     ```
4. Clean up the worktree:
   ```bash
   git -C "$HOME/repo" worktree remove --force "$WORKTREE" 2>/dev/null || true
   ```
5. Remove the session from `poller-state.json`

## Schedule

Registered as a scheduled task running every 60 seconds. This skill runs once per invocation and exits.
