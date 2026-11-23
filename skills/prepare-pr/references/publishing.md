# Publishing

## Verify

1. Find the commands: first in the repository rules, then in the project scripts (`package.json`, `Makefile`, `pyproject.toml`, `justfile` and similar). Use the package manager the repository uses.
2. Run the tests, the type check and the lint for the slice.
3. Read the output of each command. Keep the last lines for the summary.
4. If the repository has no command for one of these checks, say which check is missing. Never report a check as passed without its output.

A failure caused by your change: fix it and verify again. A failure that existed before your change: report it in the summary by name.

## The summary

When verification and review are done, show this summary and stop:

```text
READY TO PUBLISH
Branch: <branch> -> <target branch>
Changes: <path> +<added>/-<removed>, one line per file
Verification: <command> -> <result>, one line per check
Review: Standards <result>, Scope <result>
Rules: <rules that changed the plan or code, or "no rules found">
Commit and PR title: <title>
PR body: <first lines>
Later: <items, or "none">
Waiting for PO: <questions, or "none">

QUESTION: Publish?
```

## Titles and body

- Use the title format from the repository rules or the recent `git log`. If there is none, use the default below.
- Default with a ticket: `<type>(<TICKET>): <summary>`. Without a ticket: `<type>: <summary>`.
- `<type>` is the type of the slice branch. `<summary>` is lowercase, in the imperative, and says what changes for the user of the code.
- PR body: if the repository has a pull request template (for example `.github/pull_request_template.md`), fill it in. If it has none, write three short parts: what changes, why, how it was verified.

## The yes

Only a reply to this summary that clearly approves it is a yes: for example "yes", "tak", "ok, publish". An instruction given before the summary existed ("push it when the tests pass") is not a yes: the user had not seen this diff.

After the yes:

1. Before `git add`, compare `git status --porcelain` and `git diff --stat` with the files in the summary. If anything differs, including edits the user made, show a new summary and ask again.
2. `git add` the files listed in the summary, and only those. Never the plan file.
3. `git commit` with the title as the message. One commit per slice.
4. `git push -u origin <branch>`. Never force-push.
5. Open the PR against the target branch with the repository's tool (for example `gh pr create`).

If the diff changes after the yes, ask again. Show what changed since the summary and the new `QUESTION: Publish?`.

## After the PR

1. Set the slice status in the plan file to `PR open <url>`.
2. Give the user the PR link.
3. If slices remain, ask: `QUESTION: Start slice <n>: <title>?`

Do not merge, approve or close PRs. Do not change the ticket status or comment in the tracker.
