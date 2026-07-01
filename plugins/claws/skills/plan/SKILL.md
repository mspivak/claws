---
name: plan
description: Developer-invoked planner. Takes a PRD — either inline prompt text or a path to a markdown file — and runs it through specify → clarify → plan → tasks → analyze, writing durable spec/plan/tasks artifacts under specs/<NNN-slug>/ and seeding one GitHub issue per task into the Ready column. Reads project config from .claws.json and stack conventions from specs/memory/constitution.md. Run after init-project and before work-on-pending.
argument-hint: "<prd text> | path/to/prd.md"
---

# plan

The second step of the local claws workflow:

1. `init-project` — repo + project + constitution created
2. **`plan <prd>`** — specify → clarify → plan → tasks → analyze, seed tasks into Ready  ← this skill
3. `work-on-pending` — dispatch one agent per Ready card

You take a PRD from the developer and run it through five stages — specify, clarify, plan,
tasks, analyze — mirroring the spec-driven-development pipeline. Each stage's output is a
committed markdown artifact under `specs/<NNN-slug>/`, so the durable record of *why* and
*how* a feature was built lives in the repo, not only in the ephemeral issue thread. The
final stage creates one GitHub issue per task as a Ready card on the project. You read
project config from `.claws.json`, stack conventions from `specs/memory/constitution.md`,
and use the local `gh` token — no env vars, no poller, no SSM.

## Inputs

The PRD comes from the skill argument:

- If the argument is a path to an existing file (e.g. `docs/prd.md`), read that file as the PRD.
- Otherwise treat the entire argument text as the PRD itself.
- If no argument is given, stop and ask the developer for a PRD — either pasted text or a path.

Project config is resolved the same way `work-on-pending` does:

- `.claws.json` at the repo root supplies `owner` and `projectNumber` (and `projectUrl`).
- `GITHUB_REPO` comes from `gh repo view --json nameWithOwner -q .nameWithOwner`.

## Step 1 — Load the PRD

Resolve the argument to PRD text per the rule above. Read the whole thing carefully. If it
points at a file, read the full file. The PRD is the single source of truth for what to build.

## Step 2 — Load project metadata

Read `.claws.json` for `owner` and `projectNumber`. Resolve `GITHUB_REPO`:

```bash
GITHUB_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
```

Fetch the project id, status field id, and the **Ready** option id (the only status this skill
writes). Use the query matching the owner type — `user` shown; swap to `organization` for orgs.
Detect from `projectUrl` (`/users/` vs `/orgs/`); if absent, try `user` first then `organization`.

```bash
gh api graphql -f query='
  query($owner: String!, $number: Int!) {
    user(login: $owner) {
      projectV2(number: $number) {
        id
        field(name: "Status") {
          ... on ProjectV2SingleSelectField { id options { id name } }
        }
      }
    }
  }
' -f owner="$OWNER" -F number="$PROJECT_NUMBER"
```

Extract `PROJECT_ID`, `STATUS_FIELD_ID`, and the option id whose name is `Ready` (case-insensitive)
as `STATUS_READY`. If there is no `Ready` option, stop and tell the developer to run `init-project`
(or `claws setup-github`) to set up the Status field first.

## Step 3 — Load the constitution

Read `specs/memory/constitution.md` if it exists. Its Technology Stack Defaults and Core
Principles govern how you write the spec, plan, and tasks below (language choice, IaC
conventions, testing requirements, commit style, etc.) — an existing project's established
stack still wins over the constitution's defaults where the two disagree (e.g. the PRD is
for a repo that's already Go; don't push Python because the constitution defaults to it).

If the file doesn't exist, proceed without it — not every repo has run `init-project`
with this feature — but mention in the final summary that no constitution was found.

## Step 4 — Clarify

Before writing anything, walk the PRD against this checklist. For each item that's
ambiguous or unstated and would materially change the resulting tasks, ask the developer
a focused question (this skill runs in the foreground, so asking here is fine — unlike
`work-on-task`/`work-on-pending`, which must never ask):

- **Scope boundary**: what's explicitly *out* of scope for this PRD?
- **Non-functional requirements**: performance, security, or compliance constraints the
  PRD implies but doesn't state?
- **Success signal**: how will the developer know the feature is done and working?
- **Conflicting stack choice**: does the PRD imply a technology that conflicts with the
  constitution's defaults (Step 3)? If so, confirm which wins.

Batch all questions into a single round — don't trickle them one at a time. Where the PRD
is merely underspecified on details an engineer would reasonably decide (not on any of the
four items above), make a sensible assumption and record it rather than asking. If nothing
on the checklist is ambiguous, skip straight to Step 5 without asking anything.

## Step 5 — Specify

Determine the feature slug and number: list `specs/` for existing `NNN-slug` directories
(ignore `memory/`), take the highest `NNN` + 1 (zero-padded to 3 digits; `001` if none
exist), and derive `slug` as a short kebab-case name for the feature. Create
`specs/<NNN-slug>/spec.md`:

```markdown
# <Feature title>

## What & why

<2-4 sentences: what this feature is, who it's for, why it matters. Derived from the PRD
plus any answers from Step 4.>

## User-facing behavior

<Concrete description of the feature from the outside — what changes for a user or caller.
No implementation detail here; that belongs in plan.md.>

## Out of scope

- <explicitly excluded from this PRD, per Step 4>

## Assumptions

- <any assumption made in Step 4 instead of asking, and why it's a reasonable default>
```

## Step 6 — Plan

Create `specs/<NNN-slug>/plan.md`, the technical approach:

```markdown
# Plan: <Feature title>

## Approach

<How this gets built — architecture, key files/modules touched, sequencing rationale.>

## Stack

<Confirm the language/IaC/testing choices this feature uses, referencing
specs/memory/constitution.md where it applies, and calling out any deliberate deviation.>

## Risks

<Anything likely to go wrong or that needed a judgment call.>
```

## Step 7 — Tasks

Turn `plan.md` into a flat list of tasks and write `specs/<NNN-slug>/tasks.md` (one
`### <task title>` section per task, each with the same Acceptance criteria checklist
that goes into the GitHub issue in Step 9). The plan must satisfy ALL of these:

- Each task is **independently shippable** and sized for **≤4 hours** of focused work for one agent.
- Each task has a clear imperative title (verb + noun, e.g. "Add foo to bar").
- Each task body has an **Acceptance criteria** section with concrete, testable checkboxes.
- Tasks may reference each other with `depends on #N` lines when ordering matters (you won't know
  the numbers until creation — use the running list from Step 9 to backfill dependency references,
  or phrase dependencies by title and note them in a final summary comment).
- Aim for a flat decomposition. If a task would clearly take more than ~4 hours, split it. Do not
  create nested "epics" — every task is a leaf the `work-on-task` agent can complete end to end.

## Step 8 — Analyze

Before creating anything on GitHub, cross-check the three artifacts:

- Does every task in `tasks.md` trace back to a sentence in `spec.md`'s "User-facing
  behavior" or an item in `plan.md`'s "Approach"? Flag (and fix) any task that doesn't.
- Does `spec.md`'s "User-facing behavior" have full coverage in `tasks.md` — i.e. no
  described behavior is left with no task implementing it?
- Is the `depends on` graph acyclic and consistent with the demoable-slice ordering rule
  from Step 7?
- Does `plan.md`'s Stack section match what `tasks.md`'s tasks actually ask for?

If this surfaces a gap, fix `tasks.md` (and `spec.md`/`plan.md` if the gap traces back
further) before moving on — don't create GitHub issues for an inconsistent plan.

Commit the three files with a Conventional Commit (do not push):

```bash
git add "specs/<NNN-slug>/"
git commit -m "docs(specs): add spec, plan, and tasks for <feature title>"
```

## Step 9 — Create each task as a Ready card

For each planned task: create the issue, add it to the project, and move it to Ready.

```bash
TASK_URL=$(gh issue create \
  --repo "$GITHUB_REPO" \
  --title "<imperative task title>" \
  --body "## Context

Spec: specs/<NNN-slug>/spec.md
Plan: specs/<NNN-slug>/plan.md

<one paragraph: what this task delivers and why>

## Acceptance criteria

- [ ] <concrete, testable outcome>
- [ ] <concrete, testable outcome>

## Relevant files

- <path/to/file>: <why it matters>
")

TASK_NUMBER=$(basename "$TASK_URL")

TASK_ITEM_ID=$(gh api graphql -f query='
  mutation($projectId: ID!, $contentId: ID!) {
    addProjectV2ItemById(input: { projectId: $projectId, contentId: $contentId }) {
      item { id }
    }
  }
' -f projectId="$PROJECT_ID" \
  -F contentId="$(gh issue view "$TASK_NUMBER" --repo "$GITHUB_REPO" --json id -q .id)" \
  -q .data.addProjectV2ItemById.item.id)

gh api graphql -f query='
  mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $projectId
      itemId: $itemId
      fieldId: $fieldId
      value: { singleSelectOptionId: $optionId }
    }) { projectV2Item { id } }
  }
' -f projectId="$PROJECT_ID" \
  -f itemId="$TASK_ITEM_ID" \
  -f fieldId="$STATUS_FIELD_ID" \
  -f optionId="$STATUS_READY"
```

Keep a running list of `(TASK_NUMBER, TASK_TITLE, TASK_URL)` for the summary.

## Step 10 — Summary

Print a compact table of what was created and the next action:

```
Wrote specs/<NNN-slug>/{spec,plan,tasks}.md (committed, not pushed)
Constitution: specs/memory/constitution.md (found | not found — stack defaults skipped)

Seeded N task(s) into Ready on <projectUrl>:

  #12  Add foo to bar          https://github.com/<owner>/<repo>/issues/12
  #13  Wire baz into the API   https://github.com/<owner>/<repo>/issues/13

Next: run /work-on-pending to start one agent per Ready card.
```

---

## Rules

- Read the PRD in full before decomposing — do not plan from the title alone.
- Every stage's artifact is written before the next stage starts: spec.md before plan.md,
  plan.md before tasks.md. Don't skip straight to tasks from the PRD.
- Every task must be a leaf sized ≤4 hours with an explicit "Acceptance criteria" section.
- Never create nested epics and never recurse — this skill emits a flat list of leaf tasks.
- Run the Analyze cross-check (Step 8) before creating any GitHub issue — an inconsistent
  tasks.md never reaches Ready.
- Only ever set cards to **Ready** — claiming, In Progress, and review transitions belong to the
  downstream `work-on-task` agent.
- Never write application code or open a PR — this skill only writes specs/ markdown and
  creates issues and project cards. It commits the specs/ files locally but never pushes.
- Resolve all IDs from `.claws.json` + local `gh` auth. Never invent issue numbers or project IDs.
- Ask clarifying questions (Step 4) only for the four checklist items that would materially
  change the resulting tasks; otherwise record reasonable assumptions in spec.md and proceed.
