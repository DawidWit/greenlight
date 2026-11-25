---
name: prepare-pr
description: Use when implementing a ticket, issue, feature or bug fix end to end, with or without a ticket key, or when asked to prepare, open or create a pull request for changes that already exist in the working tree.
---

# Prepare PR

## Overview

Take a task from a ticket, a description or existing changes to a verified
pull request. Ask short questions instead of guessing, keep the plan in line
with the repository rules, build the best implementation, and publish only
after an explicit yes.

Talk to the user in the user's language: questions, summaries and the message
for the PO.

Show every summary and question as chat text (Markdown). Never put a report, a
summary or a question in a code block. The templates in this skill are the
Markdown source to send.

## Core Principle

**Ask instead of guessing. Obey the repository rules. Build it well. Publish
only after an explicit yes.**

## The Iron Law

```text
NO COMMIT, PUSH OR PR WITHOUT AN EXPLICIT YES
```

The explicit yes is a reply to the `READY TO PUBLISH` summary in
[references/publishing.md](references/publishing.md). Until then, all changes
stay uncommitted: no `git add`, no `git commit`, no `git push`, no PR. An
instruction given before the summary existed is not a yes. If the diff changes
after the yes, ask again.

## The Process

### Entry

Pick the entry from what the user gives you:

- **From a ticket or description:** the user names a ticket (key or link),
  describes a task, or both. Start at stage 1.
- **From existing changes:** the user asks to prepare a PR and the working tree
  already holds the changes. Work on the current branch. Start at stage 4 with
  the diff, then do stages 5 to 8. If there is no ticket and no description,
  first ask one question: what must the change do? In this mode, create the
  plan file (see [references/planning.md](references/planning.md)) with the
  source, a one-slice list and an empty Later list.

If a plan file for this ticket or task already exists in `.claude/plans/`,
read the plan file and continue from where it stops.

### Stages

1. **Ask** - [references/asking.md](references/asking.md): read the ticket,
   the code and the rules; ask one question at a time; send questions about
   behavior to the PO as a message.
2. **Slice** - [references/slicing.md](references/slicing.md): thin vertical
   slices of about 300 changed lines; one branch and one PR per slice.
3. **Plan** - [references/planning.md](references/planning.md): plan the
   current slice in `.claude/plans/`, kept out of git.
4. **Check the rules** - [references/rules-check.md](references/rules-check.md):
   correct the plan, or the diff, until it obeys every repository rule.
5. **Implement** - [references/implementing.md](references/implementing.md):
   test first, best implementation, fix weak code the task relies on.
6. **Verify** - [references/publishing.md](references/publishing.md): tests,
   type check and lint, with their output.
7. **Review** - [references/reviewing.md](references/reviewing.md): Standards
   and Scope.
8. **Publish** - [references/publishing.md](references/publishing.md): summary,
   explicit yes, commit, push, PR.

One run takes one slice to an open PR. Then ask whether to start the next one.

## Human Decision Gate

Every question to the user has this shape:

```markdown
**QUESTION:** <one short sentence>

**Recommendation:** <option> - <one-clause reason>

1. <option>
2. <option>
```

Write the recommendation and the options only when the options can be named.
Ask one question at a time and wait for the answer. Keep working on what the
question does not block.

Use the gate for: how to build something, a rule that collides with the
requirement, a bug in code whose behavior you must keep, a split into two or
more slices, publishing, and starting the next slice.

Do not use it for: a plan that breaks a rule (correct it), routine
implementation choices (decide them), and questions about behavior (write the
message for the PO).

## Common Rationalizations

| Excuse                                                    | Reality                                                                                                   |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| "The user said at the start: push when the tests pass."   | They had not seen this diff. Only a yes to the summary counts.                                            |
| "Everything is green, publishing is safe."                | Green checks are evidence, not approval. Show the summary and stop.                                       |
| "I'll ask all questions at once to save a round trip."    | A list gets partial answers. One question at a time.                                                      |
| "I'll list my defaults and ask for an ok on all of them." | A default the user skimmed is still a guess. Ask the one that changes the build; behavior goes to the PO. |
| "I need the ticket key for the commit title."             | The ticket is optional. Without a key the title is `<type>: <summary>`.                                   |
| "The goal is obvious from the diff."                      | The diff shows what the code does, not what it must do. Ask.                                              |
| "I'll change only what the new feature needs."            | Weak code the new code relies on is part of the task. Pin its behavior with a test, then fix it.          |
| "Fixing that helper is scope creep."                      | Code the task relies on is in scope. Code it does not rely on goes to Later.                              |
| "The plan breaks a rule, I'll ask whether to fix it."     | Correct the plan. Ask only when the rule collides with the requirement.                                   |

## Quick Reference

| Situation                                    | Action                                                           |
| -------------------------------------------- | ---------------------------------------------------------------- |
| Ticket key and a tracker tool                | Read the ticket with the tool                                    |
| Ticket key, no tracker tool                  | Ask the user to paste the ticket                                 |
| Existing changes, no ticket, no description  | One question: what must the change do?                           |
| Open point about how to build                | `QUESTION` to the user                                           |
| Open point about behavior                    | `MESSAGE FOR THE PO`; that part becomes a `waiting for PO` slice |
| Plan breaks a repository rule                | Correct the plan and record the rule                             |
| Rule collides with the requirement           | `QUESTION` to the user                                           |
| Weak code the task relies on                 | Pinning test, then fix                                           |
| Weak code the task does not rely on          | One line in Later                                                |
| Unrelated uncommitted changes, from a ticket | Work in a `git worktree`                                         |
| No command for a check                       | Say which check is missing                                       |
| Verification and review done                 | `READY TO PUBLISH` summary, then stop                            |
| Diff changed after the yes                   | New summary, ask again                                           |
| Plan file exists                             | Read it and continue                                             |

## Red Flags - STOP

- `git add`, `git commit`, `git push` or a PR without a yes to the current summary
- Two or more questions to the user in one message
- A list of assumptions with "reply ok to accept"
- Code that guesses behavior the ticket does not settle
- A plan step that breaks a repository rule
- Asking for a ticket key the user did not mention
- Changes to code the task does not rely on
- Touching the user's uncommitted changes that are not part of the task
- The plan file staged or committed
- "Verification passed" without command output
- Merging, approving or closing PRs, or changing the ticket status

**Any red flag: stop and go back to the stage it belongs to.**

## Common Mistakes

| Mistake                                                   | Correction                                      |
| --------------------------------------------------------- | ----------------------------------------------- |
| A question with context, assumptions and options in prose | One sentence; options in the gate               |
| Behavior questions put to the user as decisions           | `MESSAGE FOR THE PO`                            |
| Branch `SHOP-540-total-with-vat`                          | `feat/SHOP-540/total-with-vat`                  |
| Plan saved under `docs/` and committed                    | `.claude/plans/`, listed in `.git/info/exclude` |
| One large PR for the whole ticket                         | Slices of about 300 changed lines               |
| Rules invented when the repository has none               | Write "no rules found"                          |

## The Bottom Line

**Ask short. Obey the rules. Build it well. Publish only after a yes.**
