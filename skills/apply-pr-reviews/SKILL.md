---
name: apply-pr-reviews
description: Use when going through your own open pull requests, typically at the start of the day, to apply review feedback, fix failing CI, or rebase branches and stacked pull requests that conflict with their base, or when asked to handle review comments on specific pull requests.
---

# Apply PR Reviews

## Overview

Go through every open pull request the user authored in the configured
repositories. Fix review feedback that holds up against the current code, fix
CI failures the code causes, and rebase branches and stacks that conflict. Do
all of the work locally first. Then show one short report and ask once. Push
and write on GitHub only after the yes.

Talk to the user in the user's language: questions and the report. Everything
written on GitHub (commits, replies) is in English.

Show the report and every question as chat text (Markdown). Never put a
report, a summary or a question in a code block. The templates in this skill
are the Markdown source to send.

Requires Python 3.9+, Git and an authenticated GitHub CLI (`gh`).
`<skill-directory>` is the directory of this file.

## Core Principle

**Check every comment against the code. Do the work locally. Report short.
Push only after one yes.**

## The Iron Law

```text
NO PUSH AND NO GITHUB WRITE WITHOUT A YES TO THE CURRENT REPORT
```

The yes is the user's answer to the push question under the current report
([references/reporting.md](references/reporting.md)). Before it: no
`git push`, no reply in a thread, no PR comment, no base change. Local commits
in a detached worktree are allowed, because a stack can only be rebased on
committed work. An instruction given before the report existed is not a yes.
If anything changed after the report, show a new report and ask again.

## The Process

1. **Collect** - [references/collecting.md](references/collecting.md): open
   PRs, CI and merge state, stacks, one detached worktree per PR.
2. **For each PR, stacks bottom up:**
   1. **Rebase** - [references/rebasing.md](references/rebasing.md): only on a
      conflict, a changed parent or a merged parent.
   2. **Evaluate** - [references/evaluating.md](references/evaluating.md):
      each comment against the current code.
   3. **Fix** - [references/fixing.md](references/fixing.md): review items
      and CI, test first, verify, commit locally.
3. **Ask** - the collected questions, one at a time, through the Human
   Decision Gate.
4. **Report** - [references/reporting.md](references/reporting.md): one line
   per item and one push question.
5. **Publish** - [references/publishing.md](references/publishing.md): push
   with the exact lease, then replies, after the yes only.

Except for missing configuration, do not ask anything before step 3. A PR
higher in a stack is worked on only after the PR below it is final, so no SHA
changes after the report.

## Human Decision Gate

Every question to the user has this shape:

```markdown
**QUESTION:** <one short sentence>

**Recommendation:** <option> - <one-clause reason>

1. <option>
2. <option>
```

Write the recommendation and the options only when the options can be named.
Ask one question at a time and wait for the answer.

Use it for: a comment that is unclear, conflicts with another comment or
changes the architecture; a rebase conflict without a clear resolution;
missing repository configuration; the push question.

Do not use it for: a comment that breaks a repository rule (skip it with
evidence), routine implementation choices, rebase or merge (always rebase),
a PR above an excluded PR (it is excluded too), PRs that do not depend on a
rejected push (the yes still covers them).

The answer "skip" writes nothing on GitHub. The item stays 🟡 in the report and
comes back on the next run.

## Common Rationalizations

| Excuse                                                     | Reality                                                                                   |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| "The user said: push without asking."                      | They had not seen this report. Only a yes to the current report counts.                   |
| "Merging the base avoids a force push."                    | Conflicts are resolved by rebase only. The push uses the lease with the exact remote SHA. |
| "`--force-with-lease` alone is safe enough."               | Without the SHA from the report, a background fetch can let it overwrite someone's push.  |
| "Re-running only the failed job is harmless."              | Re-running CI is a GitHub write nobody asked for. Put the cause in the report.            |
| "The thread is fixed, I'll offer to resolve it."           | Threads are never resolved. A thread the author answered waits for the reviewer.          |
| "I'll ask before I start the work."                        | Do the work locally first. Ask under the report.                                          |
| "The report is old now, I'd rather confirm the other PRs." | A rejected push stops only that PR and every PR above it in the stack. Push the rest.     |
| "A full, friendly explanation helps the reviewer."         | `Not applied` is one plain sentence.                                                      |
| "While I'm here, I can also add X."                        | Do only what review or CI requires. Do not offer extra work.                              |
| "The reviewer asked for it."                               | Check it against the code and the repository rules first.                                 |

## Quick Reference

| Situation                                         | Action                                                         |
| ------------------------------------------------- | -------------------------------------------------------------- |
| No repository configuration                       | One question for local repository paths                        |
| Comment holds against the code                    | Fix, verify, 🟢, `Fixed in <sha>` after the push               |
| Comment wrong, out of scope or against a rule     | Skip, 🟡 with evidence, `Not applied: <reason>` after the push |
| Comment unclear or conflicting                    | Question after all PRs are processed                           |
| Author answered last                              | Waits for the reviewer: no change, no reply, not in the report |
| CI fails because of the code                      | Fix it, 🔴 with cause and fix                                  |
| CI fails because of the environment or flakiness  | 🔴 with the cause, no change, no re-run                        |
| Conflict with the base (local `merge-tree` check) | Rebase, never merge                                            |
| Head branch is shared (`stack.shared_head`)       | 🟡, never rebase or push it                                    |
| Parent in the stack merged                        | `rebase --onto`, base change after the yes                     |
| User excludes a PR                                | Exclude every PR above it in the stack too                     |
| Push rejected                                     | 🔴 for it and every PR above it; do not retry; push the rest   |
| Anything changed after the report                 | New report, ask again                                          |

## Red Flags - STOP

- `git push`, a reply, a PR comment or a base change before a yes to the current report
- A question before all PRs are processed
- `git merge` of the base branch into a PR branch
- `--force` or `--force-with-lease` without the remote SHA from the report
- `gh run rerun` or any other CI re-run
- Resolving a thread, or offering to
- A second reply on an item the author already answered
- A `Not applied` reply longer than one sentence
- A report with a TLDR, process narration or more than one question
- Any change in the user's checkout
- Retrying a rejected push

**Any red flag: stop and go back to the step it belongs to.**

## Common Mistakes

| Mistake                                       | Correction                                             |
| --------------------------------------------- | ------------------------------------------------------ |
| Asking for `owner/repository`                 | Ask once for local repository directories              |
| Rebasing a PR whose base only moved ahead     | Rebase only on a conflict or a stack change            |
| Working on a child before its parent is final | Stacks bottom up                                       |
| Pushing a child whose parent was excluded     | Excluded too: it carries the parent's unpushed commits |
| Report lines that explain the process         | Result only: what was fixed, skipped or broken         |
| Verification output in the report             | Only failed checks                                     |

## The Bottom Line

**Check the code. Work locally. One short report. One yes. Then push with the
exact lease and reply.**
