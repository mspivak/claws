#!/bin/bash
set -euo pipefail

PROJECT_NAME="%%project_name%%"
GITHUB_REPO="%%github_repo%%"
AWS_REGION="%%aws_region%%"
HOME_DIR="/home/ec2-user"
NVM_DIR="$HOME_DIR/.nvm"

log() { echo "[claws] $*" | tee -a /var/log/claws-init.log; }

log "Starting claws bootstrap for project=$PROJECT_NAME"

# ── 1. System packages ──────────────────────────────────────────────────────
dnf update -y -q
dnf install -y -q git jq python3-pip

# ── 2. GitHub CLI ────────────────────────────────────────────────────────────
dnf install -y -q 'dnf-command(config-manager)'
dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
dnf install -y -q gh

# ── 3. Node 22 via nvm (as ec2-user) ────────────────────────────────────────
sudo -u ec2-user bash -c "
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  source $NVM_DIR/nvm.sh
  nvm install 22
  nvm alias default 22
"

# ── 4. Claude Code CLI ───────────────────────────────────────────────────────
sudo -u ec2-user bash -c "
  source $NVM_DIR/nvm.sh
  npm install -g @anthropic-ai/claude-code
"

# ── 5. OpenClaw ──────────────────────────────────────────────────────────────
sudo -u ec2-user bash -c "
  source $NVM_DIR/nvm.sh
  npm install -g openclaw@latest
"

# ── 6. Enable systemd linger for headless operation ─────────────────────────
loginctl enable-linger ec2-user

# ── 7. SSM bootstrap script (runs before openclaw gateway starts) ────────────
cat > "$HOME_DIR/fetch-secrets.sh" << 'SCRIPT'
#!/bin/bash
set -euo pipefail
REGION="%%aws_region%%"
PREFIX="/claws/%%project_name%%"

get_param() {
  aws ssm get-parameter \
    --region "$REGION" \
    --name "$PREFIX/$1" \
    --with-decryption \
    --query Parameter.Value \
    --output text 2>/dev/null || echo ""
}

mkdir -p ~/.openclaw

BOT_TOKEN=$(get_param telegram/bot-token)
ALLOWED_IDS=$(get_param telegram/allowed-user-ids)

cat > ~/.openclaw/secrets.env << ENV
TELEGRAM_BOT_TOKEN=$BOT_TOKEN
TELEGRAM_ALLOWED_USER_IDS=$ALLOWED_IDS
GITHUB_TOKEN=$(get_param github/token)
GITHUB_ORG=$(get_param github/org)
GITHUB_REPO=$(get_param github/repo)
CLAWS_PROJECT_NAME=$(get_param github/project-number)
CLAWS_PROJECT_ID=$(get_param github/project-id)
CLAWS_STATUS_FIELD_ID=$(get_param github/status-field-id)
CLAWS_STATUS_READY=$(get_param github/status-ready)
CLAWS_STATUS_IN_PROGRESS=$(get_param github/status-in-progress)
CLAWS_STATUS_BLOCKED=$(get_param github/status-blocked)
CLAWS_STATUS_IN_REVIEW=$(get_param github/status-in-review)
ANTHROPIC_API_KEY=$(get_param anthropic/api-key)
ENV

if [ -n "$BOT_TOKEN" ] && [ "$BOT_TOKEN" != "placeholder" ]; then
  IDS_JSON=$(echo "$ALLOWED_IDS" | tr ',' '\n' | jq -R 'tonumber' | jq -sc '.')
  cat > ~/.openclaw/openclaw.json << CFG
{
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "$BOT_TOKEN",
      "dmPolicy": "allowlist",
      "allowFrom": $IDS_JSON,
      "streaming": "partial",
      "linkPreview": false
    }
  },
  "acp": {
    "enabled": true,
    "dispatch": { "enabled": true },
    "backend": "acpx",
    "defaultAgent": "claude",
    "allowedAgents": ["claude"]
  },
  "plugins": {
    "entries": {
      "acpx": {
        "config": {
          "permissionMode": "approve-all"
        }
      }
    }
  }
}
CFG
fi
SCRIPT

chmod +x "$HOME_DIR/fetch-secrets.sh"
chown ec2-user:ec2-user "$HOME_DIR/fetch-secrets.sh"

# ── 8. Clone target repo ─────────────────────────────────────────────────────
# Clone happens after secrets are available; defer to a post-boot unit instead.
# Write a one-shot service that clones once GITHUB_TOKEN is in secrets.env.
mkdir -p "$HOME_DIR/.config/systemd/user"
cat > "$HOME_DIR/.config/systemd/user/claws-clone.service" << SERVICE
[Unit]
Description=Clone target GitHub repo
After=claws-secrets.service
Requires=claws-secrets.service

[Service]
Type=oneshot
RemainAfterExit=yes
EnvironmentFile=%h/.openclaw/secrets.env
ExecCondition=bash -c '[ ! -d "%h/repo/.git" ]'
ExecStart=bash -c 'git clone https://\$GITHUB_TOKEN@github.com/$GITHUB_REPO %h/repo'
WorkingDirectory=%h

[Install]
WantedBy=default.target
SERVICE

# ── 9. OpenClaw config (bootstrap: Telegram disabled until setup-telegram runs) ─
mkdir -p "$HOME_DIR/.openclaw"
cat > "$HOME_DIR/.openclaw/openclaw.json" << 'CONFIG'
{
  "channels": {
    "telegram": {
      "enabled": false
    }
  },
  "acp": {
    "enabled": true,
    "dispatch": { "enabled": true },
    "backend": "acpx",
    "defaultAgent": "claude",
    "allowedAgents": ["claude"]
  },
  "plugins": {
    "entries": {
      "acpx": {
        "config": {
          "permissionMode": "approve-all"
        }
      }
    }
  }
}
CONFIG
chown -R ec2-user:ec2-user "$HOME_DIR/.openclaw"

# ── 10. Systemd secrets fetch service ────────────────────────────────────────
cat > "$HOME_DIR/.config/systemd/user/claws-secrets.service" << SERVICE
[Unit]
Description=Fetch claws secrets from SSM
Before=openclaw-gateway.service claws-clone.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=%h/fetch-secrets.sh

[Install]
WantedBy=default.target
SERVICE

# ── 11. Install skills ───────────────────────────────────────────────────────
SKILLS_DIR="$HOME_DIR/.openclaw/skills"
mkdir -p "$SKILLS_DIR/github-poller"
mkdir -p "$SKILLS_DIR/project-task"

cat > "$SKILLS_DIR/github-poller/skill.md" << 'SKILL'
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
SKILL

cat > "$SKILLS_DIR/project-task/skill.md" << 'SKILL'
# project-task

Non-interactive autonomous agent working on a GitHub issue in a dedicated git worktree.
Never ask the user questions. If blocked, signal via GitHub and exit.

## Inputs (environment variables)

- `CLAWS_ISSUE_NUMBER`, `CLAWS_PROJECT_ID`, `CLAWS_ITEM_ID`
- `CLAWS_STATUS_FIELD_ID`, `CLAWS_STATUS_IN_PROGRESS`, `CLAWS_STATUS_BLOCKED`, `CLAWS_STATUS_IN_REVIEW`
- `GITHUB_TOKEN`, `GITHUB_REPO`

## Step 0 — Claim the task

Move to "In Progress". If the mutation fails, exit 0 immediately.

```bash
gh api graphql -f query='mutation { updateProjectV2ItemFieldValue(input: {
  projectId: "$CLAWS_PROJECT_ID" itemId: "$CLAWS_ITEM_ID"
  fieldId: "$CLAWS_STATUS_FIELD_ID"
  value: { singleSelectOptionId: "$CLAWS_STATUS_IN_PROGRESS" }
}) { projectV2Item { id } } }'
```

## Step 1 — Read the issue

```bash
gh issue view $CLAWS_ISSUE_NUMBER --repo $GITHUB_REPO --json title,body,labels,comments
```

## Step 2 — Plan

Think through what files need to change and what the minimal change is.
If anything is ambiguous and would block completion, go to the BLOCKED flow.

## Step 3 — Write failing tests first

Write tests describing expected behavior. Run them and confirm they fail.

## Step 4 — Implement

Make the minimal code change to pass the tests. Confirm tests pass.

## Step 5 — Create PR

```bash
git add -A
git commit -m "<concise description>"
git push origin HEAD
gh pr create --repo $GITHUB_REPO --title "<issue title>" --body "Closes #$CLAWS_ISSUE_NUMBER" --base main
```

## Step 6 — Move to In Review

```bash
gh api graphql -f query='mutation { updateProjectV2ItemFieldValue(input: {
  projectId: "$CLAWS_PROJECT_ID" itemId: "$CLAWS_ITEM_ID"
  fieldId: "$CLAWS_STATUS_FIELD_ID"
  value: { singleSelectOptionId: "$CLAWS_STATUS_IN_REVIEW" }
}) { projectV2Item { id } } }'
```

Exit 0.

## BLOCKED flow

```bash
gh issue comment $CLAWS_ISSUE_NUMBER --repo $GITHUB_REPO \
  --body "**Blocked**: <explanation>\n\n**To unblock**: <specific action>"

gh api graphql -f query='mutation { updateProjectV2ItemFieldValue(input: {
  projectId: "$CLAWS_PROJECT_ID" itemId: "$CLAWS_ITEM_ID"
  fieldId: "$CLAWS_STATUS_FIELD_ID"
  value: { singleSelectOptionId: "$CLAWS_STATUS_BLOCKED" }
}) { projectV2Item { id } } }'
```

Exit 0.

## Rules

- Never use AskUserQuestion or any interactive tool
- Never ask for confirmation — proceed or signal blocked
- Work only in the current directory (the worktree)
- Never commit directly to main
SKILL

chown -R ec2-user:ec2-user "$SKILLS_DIR"

# ── 12. Install OpenClaw daemon and enable services ──────────────────────────
sudo -u ec2-user bash -c "
  source $NVM_DIR/nvm.sh
  openclaw onboard --install-daemon
"

chown -R ec2-user:ec2-user "$HOME_DIR/.config/systemd"

sudo -u ec2-user bash -c "
  systemctl --user daemon-reload
  systemctl --user enable --now claws-secrets.service
  systemctl --user enable --now claws-clone.service
  systemctl --user enable --now openclaw-gateway.service
"

# ── 13. Register github-poller cron job ──────────────────────────────────────
# Wait for gateway to be ready, then add the cron job
sudo -u ec2-user bash -c "
  source $NVM_DIR/nvm.sh
  for i in \$(seq 1 30); do
    openclaw gateway health --json 2>/dev/null | grep -q '\"status\":\"ok\"' && break
    sleep 2
  done
  openclaw cron add \
    --name github-poller \
    --every 60s \
    --system-event 'Poll GitHub project for READY tasks' \
    --session main \
    --timeout-seconds 120
"

log "Bootstrap complete"
