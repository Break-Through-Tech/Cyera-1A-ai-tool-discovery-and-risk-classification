# Issue tracker: GitHub

Issues and specs for this repository live in GitHub Issues. Use the `gh` CLI for all operations.

Repository: `Break-Through-Tech/Cyera-1A-ai-tool-discovery-and-risk-classification`

## Conventions

- Create: `gh issue create --title "..." --body "..."`
- Read: `gh issue view <number> --comments`
- List: `gh issue list --state open --json number,title,body,labels,comments`
- Comment: `gh issue comment <number> --body "..."`
- Add or remove labels: `gh issue edit <number> --add-label "..."` or `--remove-label "..."`
- Close: `gh issue close <number> --comment "..."`

Infer the repository from `git remote -v`; `gh` does this automatically inside the clone.

## Pull requests as a triage surface

**PRs as a request surface: no.**

GitHub shares one number space across issues and pull requests. Resolve an ambiguous number with `gh pr view <number>` and fall back to `gh issue view <number>`.

## Skill operations

When a skill says “publish to the issue tracker,” create a GitHub issue.

When a skill says “fetch the relevant ticket,” run:

`gh issue view <number> --comments`

## Wayfinding operations

- **Map:** one issue labeled `wayfinder:map`.
- **Decision ticket:** a child issue labeled `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`.
- **Child relationship:** use GitHub sub-issues. If unavailable, add the child to a task list in the map and add `Part of #<map>` to the child.
- **Blocking:** use GitHub native issue dependencies. If unavailable, add `Blocked by: #<number>` to the child.
- **Frontier:** open, unblocked, unassigned children of the map.
- **Claim:** `gh issue edit <number> --add-assignee @me` before beginning work.
- **Resolve:** post the decision as a comment, close the ticket, and add a linked one-line result to the map’s Decisions-so-far section.

For native dependency operations, use GitHub’s API with the blocker’s numeric database ID rather than its issue number.
