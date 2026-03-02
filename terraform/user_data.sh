#!/bin/bash
set -euo pipefail

PROJECT_NAME="${project_name}"
GITHUB_REPO="${github_repo}"
AWS_REGION="${aws_region}"
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
REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
PREFIX="/claws/${PROJECT_NAME}"

get_param() {
  aws ssm get-parameter \
    --region "$REGION" \
    --name "$PREFIX/$1" \
    --with-decryption \
    --query Parameter.Value \
    --output text 2>/dev/null || echo ""
}

mkdir -p ~/.openclaw
cat > ~/.openclaw/secrets.env << ENV
TELEGRAM_BOT_TOKEN=$(get_param telegram/bot-token)
TELEGRAM_ALLOWED_USER_IDS=$(get_param telegram/allowed-user-ids)
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
SCRIPT

# Inject PROJECT_NAME into script
sed -i "s/\${PROJECT_NAME}/$PROJECT_NAME/g" "$HOME_DIR/fetch-secrets.sh"
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

# ── 9. OpenClaw config ───────────────────────────────────────────────────────
mkdir -p "$HOME_DIR/.openclaw"
cat > "$HOME_DIR/.openclaw/openclaw.json" << 'CONFIG'
{
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "${TELEGRAM_BOT_TOKEN}",
      "dmPolicy": "allowlist",
      "allowFrom": [],
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
          "permissionMode": "approve-all",
          "maxConcurrentSessions": 4
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
  query {
    node(id: "$CLAWS_PROJECT_ID") {
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
' | jq --arg ready "$CLAWS_STATUS_READY" \
  '[.data.node.items.nodes[] | select(.fieldValueByName.optionId == $ready) | select(.content.number != null)]'
```

Take up to `$AVAILABLE` items from this list.

## Step 3 — For each READY item

For each item (`ITEM_ID`, `ISSUE_NUMBER`):

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
   - Send Telegram notification
4. If status is "In Review" or the session exited cleanly:
   - `git -C "$HOME/repo" worktree remove --force "$WORKTREE"`
5. Remove the session from `~/.openclaw/poller-state.json`

## Telegram notification format

```
⚠️ *Issue #N blocked*: <title>

<blocking comment>

<issue URL>
```

```bash
openclaw notify telegram "⚠️ *Issue #$ISSUE_NUMBER blocked*: $TITLE\n\n$COMMENT\n\n$URL"
```

## State file (`~/.openclaw/poller-state.json`)

```json
{"sessions": {"<session-id>": {"issueNumber": 42, "itemId": "PVTI_...", "worktree": "/home/ec2-user/worktrees/issue-42"}}}
```

Initialize to `{"sessions": {}}` if file doesn't exist.

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

log "Bootstrap complete"
