# claws

**Claude + AWS.** Deploys an EC2 box running [OpenClaw](https://openclaw.dev) that autonomously works GitHub project tasks using parallel Claude Code agents.

## How it works

1. `claws init` — Terraform provisions EC2, IAM, security group, SSH key, and SSM parameters
2. `claws setup-github` — Fetches GitHub project metadata and stores it in SSM
3. `claws setup-telegram` — Stores Telegram credentials in SSM and reloads OpenClaw config
4. The EC2 box runs OpenClaw as a systemd user service
5. A `github-poller` skill checks the GitHub project every 60s, claims READY tasks, and spawns Claude Code ACP sessions in isolated git worktrees
6. A `project-task` skill drives each session: it reads the issue, writes tests, implements, opens a PR, and moves the card to In Review — or signals Blocked via Telegram if it can't proceed

## Prerequisites

- AWS CLI configured with credentials
- Terraform ≥ 1.5
- GitHub CLI (`gh`) authenticated
- An SSH key at `~/.ssh/id_rsa.pub` (or specify `--ssh-public-key-path`)
- A GitHub project with at minimum: **Ready**, **In Progress**, **In Review**, **Blocked** status columns (`setup-github` can create missing ones)

## Installation

```bash
pip install .
```

## Usage

### Deploy

```bash
claws init \
  --project myapp \
  --repo myorg/myrepo \
  --region us-east-1
```

### Configure GitHub

```bash
claws setup-github \
  --project myapp \
  --token ghp_... \
  --org myorg \
  --repo myrepo \
  --project-number 1 \
  --region us-east-1
```

### Configure Telegram

```bash
claws setup-telegram \
  --project myapp \
  --bot-token 123456:ABC... \
  --allowed-user-ids 123456,789012 \
  --region us-east-1
```

### Check status

```bash
claws status --project myapp --region us-east-1
```

### Tear down

```bash
claws destroy --project myapp --region us-east-1
```

## Architecture

```
GitHub Project
     │  (poll every 60s)
     ▼
github-poller skill (OpenClaw)
     │  (spawn per task)
     ▼
Claude Code ACP session
  └── project-task skill
        ├── claims task (In Progress)
        ├── reads issue
        ├── writes tests
        ├── implements
        ├── opens PR
        └── moves to In Review (or Blocked → Telegram)
```

## SSM parameter paths

All under `/claws/{project_name}/`:

| Parameter | Description |
|---|---|
| `telegram/bot-token` | Telegram bot token |
| `telegram/allowed-user-ids` | Comma-separated user IDs |
| `github/token` | GitHub PAT |
| `github/org` | GitHub org |
| `github/repo` | org/repo |
| `github/project-number` | Project number |
| `github/project-id` | GraphQL project ID |
| `github/status-field-id` | Status field ID |
| `github/status-{ready,in-progress,blocked,in-review}` | Status option IDs |
| `anthropic/api-key` | Anthropic API key |

## Security

- Secrets stored as SSM SecureString; EC2 instance reads them via IAM instance role
- SSH access restricted to deployer's IP at `terraform apply` time
- `permissionMode: approve-all` on ACP sessions — agents run fully autonomously
