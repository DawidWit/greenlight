# Reviewing

Adapted from `review` in [mattpocock/skills](https://github.com/mattpocock/skills) (MIT). See THIRD_PARTY_NOTICES.md.

Review the slice after verification passes and before the publish summary.

## The diff

Nothing is committed yet, so review the working tree against the base of the slice:

- `git diff <base-branch>` for tracked files
- `git status --porcelain` for new files, which you read in full

## Two axes

Review on two separate axes. A change can pass one and fail the other.

- **Standards:** does the diff obey the repository rules found in [rules-check.md](rules-check.md)? Cite the rule (file and rule) for each finding. Skip what tooling enforces.
- **Scope:** does the diff do what the current slice must deliver? Use the slice in the plan file and the ticket or the user's description. Report:
  - requirements of the slice that are missing or partial
  - behavior nobody asked for (fixes to weak code the task relies on are allowed)
  - requirements that look done but are wrong

Parts of the ticket that belong to other slices are not findings.

If subagents are available, run the two axes in parallel, one subagent each, and give each one the diff commands, the rule files or the slice requirements, and a limit of 400 words. Otherwise, do the Standards axis, then the Scope axis, yourself.

## After the review

- Fix every real finding. Run verification again.
- A finding that needs a decision goes through the Human Decision Gate.
- Report both axes separately in the publish summary: the number of findings and what you fixed.
