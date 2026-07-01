# Constitution

**Version**: 1.0.0 · **Ratified**: 2026-07-01 · **Applies to**: mspivak/claws

This document is the source of truth for how agents build in this repository. It is
read by `plan` before decomposing a PRD and by `work-on-task` before writing any code.
When this file and an issue body disagree, this file wins unless the issue explicitly
overrides it and says why.

## Core principles

### I. Tests before code
Every task implements TDD: write a failing test that encodes the acceptance criteria,
watch it fail, then write the minimal code to pass it. No task is done without a test
that would have caught the bug it fixes or the behavior it adds.

### II. Minimal surface, no speculative generality
Build exactly what the task's acceptance criteria require. No config flags, abstraction
layers, or "while I'm here" refactors beyond the task's stated scope. Three similar
lines beat a premature abstraction.

### III. No defaults, explicit over implicit
Function and CLI parameters should not carry default values — callers state what they
mean. Prefer dictionary/bracket access (`d["key"]`) over `.get("key")` accessors so
missing keys fail loudly instead of silently returning `None`.

### IV. Narrow error handling
Never catch the bare `Exception` class (or equivalent broad catch-all) to paper over an
unknown failure mode. Catch the specific exception type you expect and know how to
handle; let everything else propagate.

### V. No comments
Code does not carry comments. Names, structure, and tests communicate intent. If a
comment feels necessary to explain *why* (a non-obvious constraint, a workaround for a
specific bug), that's the one exception — never comments that restate *what* the code
does.

## Technology stack defaults

These are the defaults for new projects and new components. An existing project's
established stack always wins — match what's already there rather than introducing a
second language or tool for the same job.

| Concern | Default | Notes |
|---|---|---|
| Application / service language | Python ≥ 3.9 | `typer` for CLIs, `boto3` for AWS, `pytest` for tests, `hatchling` as build backend |
| Infrastructure as code | Terraform | AWS provider pinned `~> 5.0`; one `terraform/` directory per deployable unit |
| Terraform state | Remote: S3 bucket (versioned) + DynamoDB lock table | No local state beyond throwaway single-operator scratch work |
| Cloud provider | AWS | Default region **us-west-2** unless the project has a latency/compliance reason to pin elsewhere |
| Resource tagging | Every Terraform-managed resource carries `Project` and `ManagedBy = "terraform"` tags | Enables cost tracking and safe teardown by tag |
| Secrets | AWS SSM Parameter Store (SecureString), read via IAM instance role | Never bake secrets into AMIs, env files committed to git, or Terraform variable defaults |
| CI | GitHub Actions | Tests must be green before merge; no merge on red CI |
| Version control workflow | Conventional Commits (`type(scope): description`) | See [conventionalcommits.org](https://www.conventionalcommits.org/) |

## Testing & CI requirements

- Every PR's CI run must execute the full test suite and pass before merge.
- New code paths ship with tests in the same PR — not as follow-up work.
- CI failures block merge; `pr-watcher` (or the equivalent reviewer) treats red CI as a
  Blocked signal, not a warning.

## Infrastructure & AWS conventions

- One `terraform/` root per deployable unit; no giant shared monolith module unless the
  project explicitly calls for a shared platform layer.
- `aws_region` and other environment-specific values are variables with **no default**
  — the deployer states them explicitly at `terraform apply` time or via a `.tfvars` file
  that is itself gitignored if it contains anything environment-specific.
- IAM roles are scoped to the minimum actions/resources the workload needs; no
  `*:*` policies.
- SSH/network ingress is restricted to the deployer's IP or a named security group, never
  `0.0.0.0/0`, unless the resource is intentionally public (e.g. a load balancer).

## Governance

- This constitution supersedes ad-hoc conventions discovered by reading `CLAUDE.md`,
  `AGENTS.md`, or `CONTRIBUTING.md` — those remain useful for anything this document
  doesn't cover, but on conflict this file wins.
- Amendments bump the version (semver: MAJOR for principle removal/redefinition, MINOR
  for a new principle or stack default, PATCH for wording/clarification) and update
  **Ratified** date.
- Only the repo owner amends this file. Agents may propose an amendment via a normal PR
  but never edit `specs/memory/constitution.md` directly as part of a task.
