---
name: review-prs
description: Use when reviewing other people's pull requests that wait for your review, or when asked to review a teammate's specific pull request, and you want a readable list of real problems before anything is posted on GitHub.
---

# Review PRs

## Overview

Collect the pull requests that wait for the user's review in the configured
repositories. Review each one on three axes: bugs, repository rules and the
ticket. Show a readable, numbered list of errors, each with a short reason.
Post only the comments the user picks and confirms, as one review per pull
request with event=COMMENT. The verdict (Approve or Request changes) is always
the user's own click.

Talk to the user in the user's language: the list and the questions. Comments
on GitHub are in English.

Show the list, the comment texts and every question as chat text (Markdown).
Never put a report, a summary or a question in a code block. The templates in
this skill are the Markdown source to send.

Requires Python 3.9+, Git and an authenticated GitHub CLI (`gh`).
`<skill-directory>` is the directory of this file.

## Core Principle

**Find real problems with evidence. Show them readably. Post only what the
user picks and confirms. The verdict is the user's click.**

## The Iron Law

```text
NO COMMENT ON GITHUB WITHOUT A CONFIRMED SELECTION
```

Two questions come before any write on GitHub. The first picks the errors
([references/listing.md](references/listing.md)). The second shows the exact
comment texts ([references/commenting.md](references/commenting.md)). Only a
yes to the second question makes the selection confirmed. Before it: no
`gh api` call that writes, no `gh pr review`, no `gh pr comment`. An
instruction given before the list existed ("post the comments right away") is
not a confirmation. If a text changes after the yes, show the texts again and
ask again.

## The Process

1. **Collect** - [references/collecting.md](references/collecting.md): review
   requests, your last review, threads, one read-only worktree per PR.
2. **Review** - [references/reviewing.md](references/reviewing.md): each PR on
   three axes, one subagent per PR when available.
3. **List** - [references/listing.md](references/listing.md): numbered errors
   with a short reason, then the first question.
4. **Show the comments** - [references/commenting.md](references/commenting.md):
   the exact texts of the picked errors, then the second question.
5. **Publish** - [references/commenting.md](references/commenting.md): one
   review per PR with event=COMMENT, after the yes only.

Except for missing configuration, ask nothing before step 3.

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

Use it for: missing repository configuration, the first question (which errors)
and the second question (post these texts).

Do not use it for: a verdict (never offered), routine review choices, or
whether an error belongs on the list (decide it with the evidence rule).

## Common Rationalizations

| Excuse                                          | Reality                                                                                   |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------- |
| "The user said: post the comments right away."  | They had not seen the list. Show the list, then the texts. Only a yes to the texts posts. |
| "The user picked the numbers, that is enough."  | The texts go out under their name. Show the exact texts and ask again.                    |
| "The user asked me to approve."                 | Approve is the user's click. Say so in one line and post only the comments.               |
| "A blocking bug deserves Request changes."      | The skill posts event=COMMENT only. The user picks the verdict.                           |
| "I'll offer to approve the clean PR."           | Never offer a verdict. A clean PR gets `🟢 No errors.`                                    |
| "A TLDR and headings make it clearer."          | The list is the summary. Use the template, nothing else.                                  |
| "I'll mention the style nit too."               | Only errors with evidence. Tools catch formatting and types.                              |
| "Another reviewer wrote it, I'll add my voice." | An error already in an open thread is not on the list.                                    |
| "The diff since my last review is enough."      | After a rebase or force push it shows base changes. Do a full review.                     |
| "The ticket wants more than this PR does."      | Check `related_prs` and the PR description: this PR may be one part of the ticket.        |

## Quick Reference

| Situation                                      | Action                                            |
| ---------------------------------------------- | ------------------------------------------------- |
| No repository configuration                    | `suggest-config`, then one question for the paths |
| Error with evidence                            | On the list: 🔴 bug, 🟡 rule or ticket            |
| Formatting, taste, or what tools catch         | Not on the list                                   |
| Error already in an open thread                | Not on the list                                   |
| Last review not an ancestor, or base merged in | Full review, said in the PR header                |
| Part of a ticket split into several PRs        | Missing parts are not errors                      |
| User picks numbers                             | Show the exact comment texts, ask again           |
| User says yes to the texts                     | One review per PR, event=COMMENT                  |
| Comment on a line outside the diff             | In the review body as `path:line`                 |
| User asks to approve or request changes        | One line: the user clicks it                      |

## Red Flags - STOP

- Any GitHub write before a yes to the comment texts
- `event` other than `COMMENT`, or `gh pr review --approve` / `--request-changes`
- Offering Approve or Request changes
- A list with a TLDR, headings, letters instead of numbers, or process narration
- An error without evidence, or a formatting nit
- Repeating an error from an open thread
- Comment texts that are long, decorated or full of jargon
- Any change in the user's checkout, installing dependencies or running the PR's code

**Any red flag: stop and go back to the step it belongs to.**

## Common Mistakes

| Mistake                                   | Correction                                        |
| ----------------------------------------- | ------------------------------------------------- |
| Numbering restarts for each PR            | One numbering for the whole list                  |
| Reason that restates the error            | The reason names the evidence: rule, case, ticket |
| Inline comment on a line outside the diff | GitHub rejects the review; use the review body    |
| Posting to a PR whose head moved          | Review it again and show its list again           |

## The Bottom Line

**Real errors, short reasons, readable list. Two questions. Comments only. The
user clicks the verdict.**
