# claws plugin

Bundles the local claws automation skills so they can be installed in any
project via the Claude Code plugin system, instead of being copied by hand into
`~/.claude/skills/`.

The developer workflow is three steps:

1. `/claws:init-project` — ensure-or-create the repo + GitHub Project, write `.claws.json`.
2. `/claws:plan <prd>` — decompose a PRD (inline text or a path to a markdown file) into tasks, seeded as Ready cards.
3. `/claws:work-on-pending` — dispatch one `work-on-task` agent per Ready card.

| Skill | Entry point | Auto-invocable | Purpose | Source skill |
| --- | --- | --- | --- | --- |
| `init-project` | `/claws:init-project` | yes | Bootstrap the repo + Project (idempotent ensure-or-create) and write `.claws.json`. | — |
| `plan` | `/claws:plan` | yes | Decompose a PRD (inline text or `.md` path) into ≤4h tasks, seeded as Ready cards. Reads `.claws.json`. | — (diverged) |
| `work-on-pending` | `/claws:work-on-pending` | yes | One pass over a GitHub Project's Ready column; dispatches a `work-on-task` subagent per pending card. | `skills/poll-project` |
| `work-on-task` | `/claws:work-on-task` | no (manual / file) | Takes one issue Ready → In Review in its own worktree. Read as a file by `work-on-pending`. | `skills/project-task` |

`work-on-task` sets `disable-model-invocation: true` because it expects `CLAWS_*`
inputs set by `work-on-pending` and must not auto-trigger on arbitrary prompts. It
remains runnable manually and is read as a file by `work-on-pending` via
`${CLAUDE_PLUGIN_ROOT}/skills/work-on-task/SKILL.md`.

## Install

```
/plugin marketplace add mspivak/claws
/plugin install claws@claws-skills
```

Choose **User** scope when prompted to make the skills available in every project.

## Source of truth

The repo's top-level [`skills/`](../../skills/) directory remains the canonical copy
consumed by the EC2/OpenClaw dogfooding path (`terraform/user_data.sh`, the
`github-poller`, and the test suite, which pin the lowercase `skills/<name>/skill.md`
paths). The files here are the packaged, frontmatter'd, renamed copies for plugin
distribution (see the **Source skill** column above for the mapping). The instruction
bodies are otherwise the same — when you change behaviour in one, update the other.
Exception: `plan` has diverged from `skills/project-planner` — the plugin version is the
developer-invoked, PRD-driven planner described above, while `skills/project-planner` remains
the poller-dispatched, epic-decomposition skill the OpenClaw/EC2 path still uses.
