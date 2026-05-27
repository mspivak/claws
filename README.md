# claws

**Claude + AWS.** Deploys an EC2 box running [OpenClaw](https://openclaw.dev) that autonomously works GitHub project tasks using parallel Claude Code agents.

> See [Dogfooding](#dogfooding) for how this repo uses claws to manage its own backlog.

## How it works

1. `claws init` — Terraform provisions EC2, IAM, security group, SSH key, and SSM parameters
2. `claws setup-github` — Fetches GitHub project metadata and stores it in SSM
3. `claws setup-telegram` — Stores Telegram credentials in SSM and reloads OpenClaw config
4. The EC2 box runs OpenClaw as a systemd user service
5. A `github-poller` skill checks the GitHub project every 60s, claims READY tasks, and spawns Claude Code ACP sessions in isolated git worktrees. Issues labelled `epic` are routed to the `project-planner` skill instead of `project-task`.
6. A `project-task` skill drives each session: it reads the issue, writes tests, implements, opens a PR, and moves the card to In Review — or signals Blocked via Telegram if it can't proceed
7. A `pr-watcher` skill sweeps In Review cards every 5 minutes, merges PRs that meet the policy, waits for CI on `main` to go green, and moves the card to Approved (or to Blocked on any failure)
8. A `project-planner` skill decomposes an `epic` Ready card into 3–10 child issues (each with explicit acceptance criteria, none labelled `epic`), seeds them into the project as Ready, and moves the epic to Approved

## Status lifecycle

```
Ready → In Progress → In Review → Approved
                ↘            ↘
                 Blocked     Blocked
```

- `Ready → In Progress`: `github-poller` claims the task and spawns a session
- `In Progress → In Review`: `project-task` opens a PR
- `In Review → Approved`: `pr-watcher` merges the PR and waits for `main` CI to go green
- Anything → `Blocked`: failure mode (ambiguous issue, CHANGES_REQUESTED review, failing CI, merge conflict)

The `pr-watcher` skill is configured via env vars + per-PR labels:

| Setting | Default | Effect |
|---|---|---|
| `CLAWS_WAIT_FOR_APPROVAL=true` | yes | Require ≥1 approving review AND green checks before merging |
| `CLAWS_WAIT_FOR_APPROVAL=false` |  | Merge as soon as checks are green |
| label `auto-merge` |  | Per-PR override: behave as if `CLAWS_WAIT_FOR_APPROVAL=false` |
| label `manual-merge` |  | Per-PR override: skip entirely; human merges by hand |

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

## Run from your laptop

If you don't want a long-running EC2 box, you can drive the same workflow from Claude Code on your laptop. The [`poll-project`](skills/poll-project/skill.md) skill does one pass over the project's Ready cards and dispatches a `project-task` subagent for each one (up to `maxConcurrent`, default 1).

1. Copy `.claws.example.json` to `.claws.json` at the repo root and fill in `projectNumber` / `owner`.
2. Make sure `gh auth status` works locally — the skill uses your local `gh` token (no SSM).
3. In Claude Code, invoke `/poll-project` from the repo root. Optionally wrap it in `/loop 5m /poll-project` for periodic re-polling within a session.

Each dispatched subagent runs in a sibling git worktree at `<worktreeParent>/<repo>-issue-N` on branch `issue-N`, follows the `project-task` skill, opens a PR, and moves the card to In Review (or Blocked).

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
| `github/status-{ready,in-progress,blocked,in-review,approved}` | Status option IDs (`approved` is optional — created only if the project has an "Approved" column) |
| `anthropic/api-key` | Anthropic API key |

## Security

- Secrets stored as SSM SecureString; EC2 instance reads them via IAM instance role
- SSH access restricted to deployer's IP at `terraform apply` time
- `permissionMode: approve-all` on ACP sessions — agents run fully autonomously

## Dogfooding

This repo is built using itself. The kanban board at [github.com/users/mspivak/projects/1](https://github.com/users/mspivak/projects/1) is worked by claws agents; the human (me, the PM) only writes cards and reviews PRs.

### The two-runner pattern

There are two equivalent ways to feed Ready cards to a `project-task` agent. Both share the same skill on disk and produce the same end-state on the board.

| Runner | Trigger | Skill | Use when |
|---|---|---|---|
| **OpenClaw on EC2** | systemd-scheduled cron, every 60s | [`openclaw/skills/github-poller/skill.md`](openclaw/skills/github-poller/skill.md) + [`openclaw/skills/pr-watcher/skill.md`](openclaw/skills/pr-watcher/skill.md) | Always-on. Laptop can be closed. |
| **Local Claude Code** | manual `/poll-project` in the IDE (optionally `/loop 5m /poll-project`) | [`skills/poll-project/skill.md`](skills/poll-project/skill.md) | Watching the agent in real time, iterating on the skills themselves, or burning your Max subscription instead of API credit. |

Both runners ultimately dispatch the **same** [`skills/project-task/skill.md`](skills/project-task/skill.md) — on EC2 as a fresh ACP session in `~/worktrees/issue-N/`, locally as a `general-purpose` subagent in `../<repo>-issue-N/`.

### Lifecycle (where the human touches it, where the agent does)

```
                  ┌──────────────────────────────────────────────────────┐
                  │                                                      │
   human PM       │            agent (project-task)             agent (pr-watcher)
   writes card    │                                                      │
        │         │                                                      │
        ▼         ▼                                                      ▼
   ┌────────┐  ┌─────────────┐  ┌───────────┐                      ┌──────────┐
   │ Ready  │─▶│ In Progress │─▶│ In Review │ ───────merge+CI────▶ │ Approved │
   └────────┘  └─────────────┘  └───────────┘                      └──────────┘
        ▲                              │
        │                              │ CHANGES_REQUESTED / CI red / conflict
        │                              ▼
        │                        ┌──────────┐
        └─── human unblocks ─────│ Blocked  │
             & moves to Ready    └──────────┘
                                       │
                                       │ next poll picks it up
                                       ▼
                                  (back to In Progress)
```

| Column | Who moves the card | What happens |
|---|---|---|
| **Ready** | Human (or `project-planner`, in flight as [#15](https://github.com/mspivak/claws/issues/15)) | PM writes the issue, drops it in Ready. |
| **In Progress** | Agent (`project-task`, Step 0) | Atomic claim. If two pollers race, the second exits silently. |
| **In Review** | Agent (`project-task`, Step 6) | Tests green, PR opened, plan comment posted on the issue. |
| **Blocked** | Agent (`project-task` BLOCKED flow, or `pr-watcher` on CI red / changes-requested) | Comment explains what's missing. Telegram ping fires from the OpenClaw side. |
| **Approved** | Agent (`pr-watcher`, after merge + green main CI) | Squash-merge, branch deleted, worktree torn down. |
| **Blocked → Ready** | Human, after fixing the upstream cause | The poller picks it up on the next tick and re-runs the lifecycle (resume work is [#14](https://github.com/mspivak/claws/issues/14), in flight). |

### Viewing the board

`gh project item-list 1 --owner mspivak --format json` dumps the raw board state. For a more readable view, open the project page in a browser, or run:

```bash
gh api graphql -f query='
  { user(login: "mspivak") { projectV2(number: 1) { items(first: 50) {
      nodes { content { ... on Issue { number title state } }
              fieldValueByName(name: "Status") {
                ... on ProjectV2ItemFieldSingleSelectValue { name } } } } } } }'
```

### In flight (the doc is a snapshot, not a guarantee)

The lifecycle above is the target architecture. Some pieces were still landing as this doc went in:

- **[#13](https://github.com/mspivak/claws/issues/13)** — `pr-watcher` skill that advances In Review → Approved. PR [#24](https://github.com/mspivak/claws/pull/24).
- **[#14](https://github.com/mspivak/claws/issues/14)** — Poller resumes work when a card moves Blocked → Ready.
- **[#15](https://github.com/mspivak/claws/issues/15)** — `project-planner` skill that decomposes an `epic` issue into Ready cards.

### Lessons learned

A grab-bag of things that were not obvious until they happened:

- **`pr-watcher` and `github-poller` are intentionally separate cron jobs.** When [#13](https://github.com/mspivak/claws/issues/13) was scoped, the alternative was to fold post-merge logic into `github-poller`. Keeping them split means each cron has a single responsibility, they can run on independent schedules (poller every 60s, watcher every 5m), and a bug in one doesn't stall the other. The price is one extra skill file — worth it.
- **OAuth via `claude setup-token` is the cleanest way off `ANTHROPIC_API_KEY`.** Long story in [`docs/oauth-spike.md`](docs/oauth-spike.md). Short version: don't copy `~/.claude/.credentials.json` to the box, don't bother with SSH port-forwarding the callback, don't wait for an RFC 8628 device-code flow that may never ship. Run `claude setup-token` locally, stash the year-long token in SSM, export it as `CLAUDE_CODE_OAUTH_TOKEN` from `user_data.sh`. Mind the 2026-06-15 Agent SDK billing split.
- **Overlapping cards during planning is fine — collapse them mid-flight.** Issue [#16](https://github.com/mspivak/claws/issues/16) ("Poller advances In Review cards to Approved when PR is merged externally") was closed as superseded once [#13](https://github.com/mspivak/claws/issues/13)'s `pr-watcher` landed and covered the same surface. Don't paralyze planning trying to make the backlog non-overlapping up front; close duplicates when one of them ships.
- **SSH `Host github.com` duplicate-block bug.** When adding the port-443 fallback for networks that block 22, it's tempting to append a second `Host github.com` block to `~/.ssh/config`. OpenSSH applies the **first** matching block and silently ignores later ones — so the new `Port 443` / `Hostname ssh.github.com` settings never take effect. Either merge into the existing block, or use a distinct `Host github.com-443` alias and `git remote set-url` accordingly.
