# claws plugin

Bundles the three local claws automation skills so they can be installed in any
project via the Claude Code plugin system, instead of being copied by hand into
`~/.claude/skills/`.

| Skill | Entry point | Auto-invocable | Purpose | Source skill |
| --- | --- | --- | --- | --- |
| `work-on-pending` | `/claws:work-on-pending` | yes | One pass over a GitHub Project's Ready column; dispatches a `work-on-task` subagent per pending card. | `skills/poll-project` |
| `work-on-task` | `/claws:work-on-task` | no (manual / file) | Takes one issue Ready → In Review in its own worktree. Read as a file by `work-on-pending`. | `skills/project-task` |
| `plan` | `/claws:plan` | no (manual / file) | Decomposes an `epic` issue into 3–10 Ready child issues. | `skills/project-planner` |

`work-on-task` and `plan` set `disable-model-invocation: true` because they
expect `CLAWS_*` env inputs set by a poller and must not auto-trigger on arbitrary
prompts. They remain runnable manually and are read as files by `work-on-pending` via
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
