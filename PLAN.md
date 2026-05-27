# claws — Plan

**claws** = Claude + AWS. Deploys an EC2 box running OpenClaw that autonomously works
GitHub project tasks using parallel Claude Code agents.

---

## What it does

1. `claws init` — Terraform deploys EC2 + IAM + SSM params
2. `claws setup-telegram` — stores Telegram bot token in SSM, patches OpenClaw config
3. `claws setup-github` — stores GitHub credentials + project details in SSM
4. The EC2 box runs OpenClaw as a systemd service
5. A custom OpenClaw skill polls the GitHub project for READY tasks every 60s,
   claims each task (moves to In Progress), spawns a Claude Code ACP session in
   a dedicated git worktree, and notifies via Telegram when anything lands in Blocked

---

## Repo structure

```
claws/
├── claws/                    # Python CLI (Typer)
│   ├── __init__.py
│   ├── main.py               # typer app entrypoint
│   └── commands/
│       ├── init.py           # runs terraform apply
│       ├── setup_telegram.py # writes SSM + patches openclaw config
│       ├── setup_github.py   # writes SSM params
│       ├── status.py         # queries OpenClaw ACP sessions via SSH
│       └── destroy.py        # terraform destroy
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── user_data.sh          # bootstraps EC2: node22, gh, claude, openclaw
├── openclaw/
│   ├── openclaw.json.j2      # Jinja2 template for OpenClaw config
│   └── skills/
│       └── github-poller/
│           └── skill.md      # the task-picker + ACP spawner skill
├── skills/
│   └── project-task/
│       └── skill.md          # updated non-interactive project-task skill
├── pyproject.toml
└── README.md
```

---

## Tech stack

- **CLI**: Python + [Typer](https://typer.tiangolo.com/) + [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)
- **IaC**: Terraform (AWS provider)
- **Orchestrator**: OpenClaw (npm, systemd user service)
- **Agent runner**: Claude Code CLI via ACP (`permissionMode: approve-all`)
- **Isolation**: git worktrees (one per task)
- **Secrets**: AWS SSM Parameter Store (SecureString), read via IAM instance role
- **Notifications**: Telegram (OpenClaw built-in channel)

---

## SSM parameter paths

All under `/claws/{project_name}/`:

| Parameter | Type | Description |
|-----------|------|-------------|
| `telegram/bot-token` | SecureString | Telegram bot token from @BotFather |
| `telegram/allowed-user-ids` | String | Comma-separated numeric Telegram user IDs |
| `github/token` | SecureString | GitHub PAT (repo + project scopes) |
| `github/org` | String | GitHub org name |
| `github/repo` | String | GitHub repo (org/name) |
| `github/project-number` | String | Project number (integer) |
| `github/project-id` | String | GraphQL project ID (PVT_...) |
| `github/status-field-id` | String | GraphQL status field ID |
| `github/status-ready` | String | Option ID for "Ready" |
| `github/status-in-progress` | String | Option ID for "In Progress" |
| `github/status-blocked` | String | Option ID for "Blocked" |
| `github/status-in-review` | String | Option ID for "In Review" |
| `github/status-approved` | String | Option ID for "Approved" (terminal state; optional if project has no "Approved" column) |
| `anthropic/api-key` | SecureString | Anthropic API key for Claude Code |

---

## Terraform (`terraform/`)

### Resources to create

- `aws_instance` — t3.large, Amazon Linux 2023, `user_data.sh`
- `aws_iam_instance_profile` + `aws_iam_role` — allows `ssm:GetParameter` and
  `ssm:GetParametersByPath` on `/claws/{project}/*`
- `aws_security_group` — outbound unrestricted, inbound SSH only from deployer IP
- `aws_ssm_parameter` (one per param above) — created empty, filled by setup commands
- `aws_key_pair` — uses `~/.ssh/id_rsa.pub` by default, configurable

### Variables (`variables.tf`)

```hcl
variable "project_name" {}          # used as SSM prefix + name tag
variable "aws_region"   {}          # no default — must be explicit
variable "instance_type" { default = "t3.large" }
variable "github_repo"  {}          # org/repo to clone on the box
variable "ssh_public_key_path" { default = "~/.ssh/id_rsa.pub" }
```

### `user_data.sh` — what it does

```bash
# 1. Install Node 22 (nvm), Claude Code CLI, GitHub CLI, Git
# 2. npm install -g openclaw@latest
# 3. sudo loginctl enable-linger ec2-user   (systemd linger for headless)
# 4. Clone the target GitHub repo to /home/ec2-user/repo
# 5. Write openclaw config stub (Telegram + ACP enabled, reads SSM at runtime)
# 6. openclaw onboard --install-daemon      (installs systemd user service)
# 7. Install the github-poller skill
# 8. Install the project-task skill
# 9. systemctl --user enable --now openclaw-gateway
```

The OpenClaw config reads SSM values via a small bootstrap script that runs before
the gateway starts (`ExecStartPre` in the systemd unit), writes them to
`~/.openclaw/secrets.env`, and the gateway loads that file.

---

## OpenClaw config template (`openclaw/openclaw.json.j2`)

```json5
{
  channels: {
    telegram: {
      enabled: true,
      botToken: "${TELEGRAM_BOT_TOKEN}",
      dmPolicy: "allowlist",
      allowFrom: [/* filled from SSM at boot */],
      streaming: "partial",
      linkPreview: false,
    },
  },
  acp: {
    enabled: true,
    dispatch: { enabled: true },
    backend: "acpx",
    defaultAgent: "claude",
    allowedAgents: ["claude"],
  },
  plugins: {
    entries: {
      acpx: {
        config: {
          permissionMode: "approve-all",
          maxConcurrentSessions: 4,
        }
      }
    }
  },
}
```

---

## github-poller skill (`openclaw/skills/github-poller/skill.md`)

This OpenClaw skill runs on a schedule (every 60s). It:

1. Reads SSM params (GitHub token, project ID, status option IDs) from env
2. Queries GitHub project API for items with status == Ready
3. For each READY item (up to `maxConcurrentSessions` minus active workers):
   a. Atomically claims the task: moves status to In Progress via GraphQL mutation
   b. Creates a git worktree: `git worktree add ~/worktrees/issue-{N} main`
   c. Spawns a Claude Code ACP session in that worktree:
      `/acp spawn claude --worktree ~/worktrees/issue-{N} --skill project-task --issue {N}`
4. Monitors ACP sessions; when one finishes:
   - On success: cleans up worktree
   - On blocked signal (agent posts BLOCKED comment + moves card): sends Telegram message

The "blocked signal" is detected by polling the issue status. If an item that was
In Progress moves to Blocked, notify Telegram with the issue URL and blocking comment.

---

## project-task skill (`skills/project-task/skill.md`)

**Key changes from the current Lumen version:**

1. **Never use `AskUserQuestion`** — when anything is unclear:
   ```bash
   gh issue comment {NUMBER} --body "**Blocked**: {explanation}\n\n**To unblock**: {specific action}"
   gh api graphql -f query='mutation { updateProjectV2ItemFieldValue(input: {
     projectId: "{PROJECT_ID}" itemId: "{ITEM_ID}"
     fieldId: "{STATUS_FIELD_ID}"
     value: { singleSelectOptionId: "{BLOCKED_OPTION_ID}" }
   }) { projectV2Item { id } } }'
   exit 0
   ```

2. **Claim task atomically at the very start** before doing any work (moves to In Progress).
   If move fails (already claimed), exit immediately.

3. **Work in a worktree** — the working directory is already set by the poller. The
   skill receives the issue number as an argument and uses `pwd` as the worktree root.

4. **Read all project/status IDs from env vars** set by the poller:
   `CLAWS_PROJECT_ID`, `CLAWS_STATUS_FIELD_ID`, `CLAWS_STATUS_READY`,
   `CLAWS_STATUS_IN_PROGRESS`, `CLAWS_STATUS_BLOCKED`, `CLAWS_STATUS_IN_REVIEW`

5. The rest of the workflow (TDD, PR creation, move to In Review) stays the same.

---

## CLI commands (`claws/commands/`)

### `claws init`

```
claws init --project myapp --repo wedoers/lumen --region us-east-1
```

- Checks AWS credentials
- Runs `terraform init && terraform apply` in `terraform/` with vars from args
- Outputs SSH command to connect + OpenClaw gateway URL

### `claws setup-telegram`

```
claws setup-telegram --project myapp --bot-token TOKEN --allowed-user-ids 123456,789012
```

- Writes SSM SecureString params
- SSHes into the box, triggers OpenClaw config reload (`openclaw gateway reload`)

### `claws setup-github`

```
claws setup-github --project myapp \
  --token ghp_... \
  --org wedoers \
  --repo lumen \
  --project-number 1
```

- Fetches project ID, status field ID, and all option IDs automatically via `gh api graphql`
- Checks for a "Blocked" column — if missing, offers to create it
- Writes all SSM params
- Triggers config reload on the box

### `claws status`

```
claws status --project myapp
```

- SSHes into box, queries `openclaw acp status`
- Shows active sessions, current issues, worktrees

### `claws destroy`

```
claws destroy --project myapp
```

- Asks for confirmation
- Runs `terraform destroy`

---

## pyproject.toml

```toml
[project]
name = "claws"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "typer>=0.12",
  "boto3>=1.34",
  "jinja2>=3.1",
  "rich>=13",
]

[project.scripts]
claws = "claws.main:app"
```

---

## GitHub project requirement

The target GitHub project **must have a "Blocked" column** in addition to the
standard columns. `claws setup-github` will detect if it's missing and create it.

---

## Implementation order

1. `pyproject.toml` + `claws/main.py` (Typer app skeleton)
2. `terraform/` (main.tf, variables.tf, outputs.tf, user_data.sh)
3. `openclaw/openclaw.json.j2`
4. `claws/commands/init.py`
5. `claws/commands/setup_github.py` (most complex — fetches IDs, creates Blocked col)
6. `claws/commands/setup_telegram.py`
7. `claws/commands/status.py`
8. `claws/commands/destroy.py`
9. `skills/project-task/skill.md` (non-interactive version)
10. `openclaw/skills/github-poller/skill.md`
11. Wire `user_data.sh` to install both skills
12. README.md

---

## Notes

- Never hardcode AWS region — always require it as a CLI arg or read from env
- SSM params are created as placeholders by Terraform; `setup-*` commands fill them
- The box pulls the target repo at boot using the GitHub token from SSM
- OpenClaw gateway hot-reloads config — no restart needed after `setup-*` commands
- `permissionMode: approve-all` is required for unattended ACP sessions
- `sudo loginctl enable-linger ec2-user` is critical for headless systemd persistence
