---
name: init-project
description: Interactive front-door that bootstraps the local claws workflow — ensure-or-create the git repo (local + GitHub), ensure-or-create the GitHub Project with the required Status options, and write .claws.json. Run this once before work-on-pending. Idempotent: detects and reuses anything that already exists. Named init-project to avoid colliding with Claude Code's built-in /init and the `claws init` Terraform CLI command.
argument-hint: "[owner=NAME] [repo=NAME] [projectTitle=\"...\"] [projectNumber=N] [visibility=private|public]"
---

# init-project

The setup step that `work-on-pending` assumes but does not perform. It takes a fresh
directory (or an existing repo) and guarantees the three things the dogfooding loop needs:

1. a git repository, locally **and** on GitHub
2. a GitHub Project whose Status field carries the option set the skills move cards between
3. a `.claws.json` pointing `work-on-pending` at that project

Unlike `work-on-task` and `plan`, this skill is **interactive** — it is run by the operator
from Claude Code, so it may confirm before any create/overwrite. It is **idempotent**: every
step detects what already exists and reuses it, only creating what is missing.

## Inputs

Resolved in this order (first non-empty wins): skill args → `.claws.json` at cwd → prompt/detect.

- `owner` — GitHub org or user that owns the repo and project. Defaults to the authenticated `gh` account.
- `repo` — repository name (not `owner/repo`). Defaults to the current directory name.
- `projectTitle` — title for the Project. Defaults to the repo name.
- `projectNumber` — if set, reuse this existing project instead of matching by title.
- `visibility` — `private` (default) or `public`, used only when creating a new repo.

## Step 0 — Preconditions

```bash
gh auth status
```

`gh` must be authenticated and the token must include both `repo` and `project` scopes. If the
`project` scope is missing, stop and tell the operator to run:

```bash
gh auth refresh -s repo,project
```

Do not try to recover from a missing scope — exit with that instruction.

## Step 1 — Ensure the local git repo

```bash
git rev-parse --is-inside-work-tree 2>/dev/null
```

If this fails, the current directory is not a repo. Confirm with the operator, then:

```bash
git init
```

If the repo has no commits yet, create an initial empty commit so a branch (`main`) exists for
worktrees to fork from later:

```bash
git symbolic-ref HEAD refs/heads/main
git commit --allow-empty -m "Initial commit"
```

Skip the commit if `git log -1` already succeeds.

## Step 2 — Ensure the GitHub repo

Detect an existing remote first:

```bash
gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null
```

If that prints `owner/repo`, the remote already exists — reuse it and set `OWNER`/`REPO` from it.

If it fails, there is no GitHub repo wired to this checkout. Resolve `OWNER` (arg → `gh api user -q .login`)
and `REPO` (arg → current directory name), confirm visibility with the operator, then create and push:

```bash
gh repo create "$OWNER/$REPO" --"$VISIBILITY" --source=. --remote=origin --push
```

`--source=.` adopts the existing checkout, `--remote=origin` wires the remote, `--push` publishes `main`.

Determine whether the owner is a user or an organisation — the project GraphQL queries differ:

```bash
gh api graphql -f query='query($owner:String!){ repositoryOwner(login:$owner){ __typename } }' \
  -f owner="$OWNER" -q .data.repositoryOwner.__typename
```

`User` or `Organization`. Call this `$OWNER_TYPE`.

## Step 3 — Ensure the GitHub Project

If `projectNumber` was provided, reuse it. Otherwise look for a project whose title matches `projectTitle`:

```bash
gh project list --owner "$OWNER" --format json \
  | jq --arg t "$PROJECT_TITLE" '.projects[] | select(.title == $t) | {number, url, id}'
```

If exactly one matches, reuse it. If none match, create one:

```bash
gh project create --owner "$OWNER" --title "$PROJECT_TITLE" --format json
```

Capture `number`, `url`, and `id` from the JSON. Then link the project to the repo so it shows on the repo's Projects tab:

```bash
gh project link "$PROJECT_NUMBER" --owner "$OWNER" --repo "$OWNER/$REPO"
```

Linking is best-effort — if it fails (already linked, or insufficient scope), warn and continue.

## Step 4 — Ensure the Status field options

A new project ships a `Status` single-select field with `Todo / In Progress / Done`. The claws
skills move cards between a different set, so the field must carry **all** of:

`Ready` · `In Progress` · `In Review` · `Blocked` · `Approved`

Fetch the field id and current options. Use the query matching `$OWNER_TYPE` (`user` shown; swap to `organization` for orgs):

```bash
gh api graphql -f query='
  query($owner:String!, $number:Int!){
    user(login:$owner){
      projectV2(number:$number){
        id
        field(name:"Status"){
          ... on ProjectV2SingleSelectField { id options { id name } }
        }
      }
    }
  }
' -f owner="$OWNER" -F number="$PROJECT_NUMBER"
```

Record `projectV2.id` as `$PROJECT_ID` and the field `id` as `$STATUS_FIELD_ID`.

If every required option is already present, skip ahead — nothing to do. Otherwise warn the
operator that **overwriting the Status options clears the status of any existing items**
(harmless on a fresh project), confirm, then set the full canonical set in one mutation:

```bash
cat <<'JSON' | gh api graphql --input -
{
  "query": "mutation($fieldId: ID!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) { updateProjectV2Field(input: { fieldId: $fieldId, singleSelectOptions: $options }) { projectV2Field { ... on ProjectV2SingleSelectField { id options { id name } } } } }",
  "variables": {
    "fieldId": "STATUS_FIELD_ID_HERE",
    "options": [
      {"name": "Ready",       "color": "GREEN",  "description": ""},
      {"name": "In Progress", "color": "YELLOW", "description": ""},
      {"name": "In Review",   "color": "BLUE",   "description": ""},
      {"name": "Blocked",     "color": "RED",    "description": ""},
      {"name": "Approved",    "color": "PURPLE", "description": ""}
    ]
  }
}
JSON
```

Substitute the real `$STATUS_FIELD_ID` for `STATUS_FIELD_ID_HERE` before sending. The mutation
returns the new options with their ids — confirm all five names are present in the response.

This matches the contract enforced by `claws setup-github` for the remote/EC2 path, so a project
bootstrapped here is also valid for the OpenClaw poller. (`Approved` is included so `pr-watcher`
can advance merged cards to the terminal state.)

## Step 5 — Write .claws.json

If `.claws.json` already exists, show its contents and confirm before overwriting. Write:

```bash
cat > .claws.json <<JSON
{
  "projectUrl": "$PROJECT_URL",
  "projectNumber": $PROJECT_NUMBER,
  "owner": "$OWNER",
  "maxConcurrent": 1,
  "worktreeParent": ".."
}
JSON
```

`projectUrl` is the `url` captured in Step 3 (its `/users/` vs `/orgs/` segment is how
`work-on-pending` picks the right GraphQL query). `.claws.json` is committed to the repo;
`.claws/` (runtime state) is gitignored.

## Step 6 — Summary

Print what was created versus reused, then the next action:

```
Repo:    <owner>/<repo>        (created | reused)
Project: <url>  #<number>      (created | reused)
Status:  Ready, In Progress, In Review, Blocked, Approved   (set | already present)
Config:  .claws.json written

Next: add a Ready card to the project, then run /work-on-pending.
```

---

## Rules

- Idempotent ensure-or-create only — never blind-create. Detect and reuse an existing repo,
  project, or option set before creating anything.
- Confirm before every irreversible action: `git init`, `gh repo create`, overwriting the Status
  options, overwriting an existing `.claws.json`.
- Never delete a repo or project. This skill only creates and wires.
- Never push application code or open PRs — it publishes at most the initial empty commit.
- If the `project` scope is missing, exit with the `gh auth refresh` instruction; do not work around it.
- Keep the Status option set identical to the one in `claws setup-github` so local and remote runners agree.
