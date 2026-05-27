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
- `CLAWS_STATUS_APPROVED`

## Step 1 — Check capacity

Read `~/.openclaw/poller-state.json` (initialize to `{"sessions":{}}` if missing).

Count the entries in `.sessions` — this is the number of currently active sessions.
MAX=4. If `active >= MAX`, exit — nothing to do.

Each session entry has the shape:

```json
{
  "issueNumber": 42,
  "itemId": "PVTI_...",
  "worktree": "/home/ec2-user/worktrees/issue-42",
  "label": "poller-issue-42",
  "lastStatus": "<status option ID>",
  "lastBlockedCommentId": null,
  "lastBlockedAt": null
}
```

`lastStatus` is the status option ID (one of the `CLAWS_STATUS_*` values) that the poller last observed for this issue. `lastBlockedCommentId` and `lastBlockedAt` are populated in Step 4 when the poller observes a transition into Blocked, so resume can detect new comments.

## Step 1.5 — Resume Blocked → Ready transitions

For each entry in `poller-state.json.sessions` whose `lastStatus == CLAWS_STATUS_BLOCKED`, query the current status from the project:

```bash
source ~/.openclaw/secrets.env
gh api graphql -f query='
  query($itemId: ID!) {
    node(id: $itemId) {
      ... on ProjectV2Item {
        fieldValueByName(name: "Status") {
          ... on ProjectV2ItemFieldSingleSelectValue { optionId }
        }
      }
    }
  }
' -f itemId="$ITEM_ID" \
| jq -r '.data.node.fieldValueByName.optionId'
```

If the returned option ID equals `CLAWS_STATUS_READY`, this is a resume — handle it like a new task but reuse the worktree and use the resume-flavoured task message.

### 1.5a — Reuse or recreate the worktree

```bash
source ~/.openclaw/secrets.env
WORKTREE="$HOME/worktrees/issue-$ISSUE_NUMBER"
BRANCH="issue-$ISSUE_NUMBER"
RESUME_FRESH=false

if [ ! -d "$WORKTREE" ]; then
  if git -C "$HOME/repo" show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git -C "$HOME/repo" worktree add "$WORKTREE" "$BRANCH"
  elif git -C "$HOME/repo" show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    git -C "$HOME/repo" worktree add "$WORKTREE" -b "$BRANCH" "origin/$BRANCH"
  else
    git -C "$HOME/repo" worktree add "$WORKTREE" -b "$BRANCH" origin/main
    RESUME_FRESH=true
  fi
fi
```

If the branch is gone from both local and origin (case 3), the prior work is unrecoverable — set `RESUME_FRESH=true` so the spawned session is started as a brand-new task rather than a resume.

### 1.5b — Spawn a resume ACP session

Use the `sessions_spawn` tool. The env block includes `CLAWS_RESUME=true` and `CLAWS_LAST_BLOCKED_COMMENT_ID` so the worker reads only comments newer than the block:

```json
{
  "runtime": "acp",
  "agentId": "claude",
  "mode": "oneshot",
  "label": "poller-issue-<ISSUE_NUMBER>-resume",
  "cwd": "/home/ec2-user/worktrees/issue-<ISSUE_NUMBER>",
  "task": "Read ~/.openclaw/skills/project-task/skill.md and follow it exactly. This issue was previously Blocked and has moved back to Ready. Follow Step 0.5 — Resume mode before reading the issue.\n\nEnvironment:\nCLAWS_ISSUE_NUMBER=<ISSUE_NUMBER>\nCLAWS_PROJECT_ID=<CLAWS_PROJECT_ID>\nCLAWS_ITEM_ID=<ITEM_ID>\nCLAWS_STATUS_FIELD_ID=<CLAWS_STATUS_FIELD_ID>\nCLAWS_STATUS_IN_PROGRESS=<CLAWS_STATUS_IN_PROGRESS>\nCLAWS_STATUS_BLOCKED=<CLAWS_STATUS_BLOCKED>\nCLAWS_STATUS_IN_REVIEW=<CLAWS_STATUS_IN_REVIEW>\nGITHUB_REPO=<GITHUB_REPO>\nCLAWS_RESUME=true\nCLAWS_LAST_BLOCKED_COMMENT_ID=<lastBlockedCommentId>\nCLAWS_LAST_BLOCKED_AT=<lastBlockedAt>"
}
```

If `RESUME_FRESH=true`, omit `CLAWS_RESUME`, `CLAWS_LAST_BLOCKED_COMMENT_ID`, and `CLAWS_LAST_BLOCKED_AT` from the env block and use the standard non-resume task wording from Step 3b.

After spawn, in `poller-state.json`:

- Remove the old (now-completed) session entry for this issue
- Record the new spawn's session key with `lastStatus` set to `CLAWS_STATUS_IN_PROGRESS` (the worker's first action will be to claim the card), and clear `lastBlockedCommentId` / `lastBlockedAt`

Decrement available capacity by 1 for each resume spawned. If `active >= MAX` again, exit before Step 2.

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

Record the returned session key → issue mapping in `~/.openclaw/poller-state.json`. Set `lastStatus` to `CLAWS_STATUS_IN_PROGRESS` (the worker claims the card in its Step 0):

```json
{
  "sessions": {
    "<session-key>": {
      "issueNumber": 42,
      "itemId": "PVTI_...",
      "worktree": "/home/ec2-user/worktrees/issue-42",
      "label": "poller-issue-42",
      "lastStatus": "<CLAWS_STATUS_IN_PROGRESS>",
      "lastBlockedCommentId": null,
      "lastBlockedAt": null
    }
  }
}
```

## Step 4 — Monitor completed sessions

Use the `sessions_list` tool with `{"kinds": ["acp"], "activeMinutes": 5}` to get recently active sessions.
Build a set of active session keys from the result.

For each session tracked in `poller-state.json` whose key is NOT in that set:

1. Look up the issue number from `poller-state.json`
2. Check the issue's current status in the GitHub project via GraphQL
3. If status is "Blocked":
   - Read the latest comment from the issue (id and timestamp)
   - Send Telegram notification:
     ```bash
     openclaw notify telegram "⚠️ *Issue #$ISSUE_NUMBER blocked*: $TITLE\n\n$COMMENT\n\n$URL"
     ```
   - Update the session entry in `poller-state.json`: set `lastStatus` to `CLAWS_STATUS_BLOCKED`, set `lastBlockedCommentId` to that comment's GraphQL node ID, set `lastBlockedAt` to its `createdAt` timestamp. Keep the worktree on disk and KEEP the session entry — Step 1.5 needs it to detect a future Blocked → Ready transition.
4. Otherwise (any non-Blocked terminal status, e.g. In Review / Approved / Done):
   - Clean up the worktree:
     ```bash
     git -C "$HOME/repo" worktree remove --force "$WORKTREE" 2>/dev/null || true
     ```
   - Remove the session from `poller-state.json`

## Schedule

Registered as a scheduled task running every 60 seconds. This skill runs once per invocation and exits.
