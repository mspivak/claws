---
name: plan
description: Developer-invoked planner. Takes a PRD — either inline prompt text or a path to a markdown file — decomposes it into small, actionable tasks, and seeds them directly into the GitHub Project's Ready column. Reads project config from .claws.json. Run after init-project and before work-on-pending.
argument-hint: "<prd text> | path/to/prd.md"
---

# plan

The second step of the local claws workflow:

1. `init-project` — repo + project created
2. **`plan <prd>`** — decompose a PRD into tasks, seed them into Ready  ← this skill
3. `work-on-pending` — dispatch one agent per Ready card

You take a PRD from the developer, break it into small, independently-shippable tasks, and
create one GitHub issue per task as a Ready card on the project. You read project config from
`.claws.json` and use the local `gh` token — no env vars, no poller, no SSM.

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

## Step 3 — Decompose

Turn the PRD into a flat list of tasks. The plan must satisfy ALL of these:

- Each task is **independently shippable** and sized for **≤4 hours** of focused work for one agent.
- Each task has a clear imperative title (verb + noun, e.g. "Add foo to bar").
- Each task body has an **Acceptance criteria** section with concrete, testable checkboxes.
- Tasks may reference each other with `depends on #N` lines when ordering matters (you won't know
  the numbers until creation — use the running list from Step 4 to backfill dependency references,
  or phrase dependencies by title and note them in a final summary comment).
- Aim for a flat decomposition. If a task would clearly take more than ~4 hours, split it. Do not
  create nested "epics" — every task is a leaf the `work-on-task` agent can complete end to end.
- **Order for an early demoable slice.** The first cards should form a thin end-to-end vertical
  slice the developer can run or click as soon as possible — not horizontal layers (all-backend,
  then all-frontend). Front-load whatever makes the feature testable soonest, even if parts are
  stubbed; defer depth and polish to later cards. When the PRD spans phases, mark the boundary in
  the title (e.g. `[P1a] …`) and gate later phases behind the slice with `depends on #N`.

If the PRD is too thin to derive concrete tasks, ask the developer focused clarifying questions
before creating anything — this skill runs in the foreground, so it is fine to ask here (unlike
`work-on-task`/`work-on-pending`, which must never ask). Where the PRD is merely underspecified
on details an engineer would reasonably decide, make a sensible assumption and record it in the
task body under an **Assumptions** heading rather than blocking.

## Step 4 — Create each task as a Ready card

For each planned task: create the issue, add it to the project, and move it to Ready.

```bash
TASK_URL=$(gh issue create \
  --repo "$GITHUB_REPO" \
  --title "<imperative task title>" \
  --body "## Context

Source PRD: <file path, or 'provided inline'>

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

## Step 5 — Summary

Print a compact table of what was created and the next action:

```
Seeded N task(s) into Ready on <projectUrl>:

  #12  Add foo to bar          https://github.com/<owner>/<repo>/issues/12
  #13  Wire baz into the API   https://github.com/<owner>/<repo>/issues/13

Next: run /work-on-pending to start one agent per Ready card.
```

---

## Rules

- Read the PRD in full before decomposing — do not plan from the title alone.
- Every task must be a leaf sized ≤4 hours with an explicit "Acceptance criteria" section.
- Never create nested epics and never recurse — this skill emits a flat list of leaf tasks.
- Only ever set cards to **Ready** — claiming, In Progress, and review transitions belong to the
  downstream `work-on-task` agent.
- Never write code or open a PR — this skill only creates issues and project cards.
- Resolve all IDs from `.claws.json` + local `gh` auth. Never invent issue numbers or project IDs.
- Ask clarifying questions only when the PRD is too vague to produce concrete tasks; otherwise
  record reasonable assumptions in the task body and proceed.
