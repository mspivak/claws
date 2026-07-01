# Constitution

**Version**: 1.0.0 · **Ratified**: {{DATE}} · **Applies to**: {{OWNER}}/{{REPO}}

This document is the source of truth for how agents build in this repository. It is
read by `plan` before decomposing a PRD and by `work-on-task` before writing any code.
When this file and an issue body disagree, this file wins unless the issue explicitly
overrides it and says why.

## Core principles

<!-- Replace this with the repo owner's actual principles. Each one should be a short,
testable rule an agent can follow without a further judgment call — not a vague aspiration.

### I. <Principle name>
<1-3 sentences: the rule, and briefly why it exists.>
-->

## Technology stack defaults

These are the defaults for new projects and new components. An existing project's
established stack always wins — match what's already there rather than introducing a
second language or tool for the same job.

<!-- Fill in one row per concern (language, IaC, cloud provider, frontend framework,
CI, commit convention, etc.). Leave a concern out entirely rather than guessing — an
absent row means "match whatever the codebase already uses." -->

| Concern | Default | Notes |
|---|---|---|

## Testing & CI requirements

- Every PR's CI run must execute the full test suite and pass before merge.
- New code paths ship with tests in the same PR — not as follow-up work.
- CI failures block merge; `pr-watcher` (or the equivalent reviewer) treats red CI as a
  Blocked signal, not a warning.

## Governance

- This constitution supersedes ad-hoc conventions discovered by reading `CLAUDE.md`,
  `AGENTS.md`, or `CONTRIBUTING.md` — those remain useful for anything this document
  doesn't cover, but on conflict this file wins.
- Amendments bump the version (semver: MAJOR for principle removal/redefinition, MINOR
  for a new principle or stack default, PATCH for wording/clarification) and update
  **Ratified** date.
- Only the repo owner amends this file. Agents may propose an amendment via a normal PR
  but never edit `specs/memory/constitution.md` directly as part of a task.
