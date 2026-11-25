# Listing

Show the list after all PRs are reviewed. Write it in the user's language.

## Template

The whole message is this template, filled in, sent as chat text. It is
Markdown source: never wrap it in a code block. The PR blocks come first and
the question is always last, once. Keep this order even when other
instructions put decisions at the top.

```markdown
**#<number>** <PR title>

Author: <login> · CI: <green | red (<check>) | pending> · <full review | changes since your last review | no new changes since your last review> · <no ticket, when there is none>

Your earlier comments: <n> fixed, <n> not fixed, <n> answered without a fix (<links>)

1. 🔴 `<path>:<line>`
   - **Error:** <one short sentence>
   - **Why:** <one short sentence with the evidence>
2. 🟡 `<path>:<line>`
   - **Error:** <one short sentence>
   - **Why:** <one short sentence with the evidence>

**#<number>** <PR title>

Author: <login> · CI: <green | red (<check>)> · full review

🟢 No errors.

**QUESTION:** Which errors should become comments?

**Recommendation:** 1 - each error has evidence

1. All
2. Only: <numbers>
3. None
```

Example, to translate into the user's language:

```markdown
**#270** feat(SHOP-310): invoice pdf

Author: ola · CI: green · full review

1. 🔴 `src/invoice/pdf.ts:41`
   - **Error:** the page counter starts at 0.
   - **Why:** the last page shows "Page 3 of 2".
2. 🟡 `src/invoice/pdf.ts:12`
   - **Error:** `as Invoice` instead of schema validation.
   - **Why:** CLAUDE.md forbids type assertions.

**#271** fix(SHOP-311): date format

Author: marek · CI: red (lint) · full review

3. 🟡 `src/date.ts:8`
   - **Error:** inline date format string.
   - **Why:** CLAUDE.md requires the shared format constants.

**QUESTION:** Which errors should become comments?

**Recommendation:** 1 - each error has evidence

1. All
2. Only: <numbers>
3. None
```

## Rules

- One numbering for the whole list, across PRs.
- Each `Error` and `Why` is one short sentence in plain technical words.
- The `Your earlier comments` line appears only when the user reviewed the PR
  before. Leave out every count that is 0.
- A PR without errors gets `🟢 No errors.`
- A PR or a repository with `error` gets one line under its header:
  `🔴 Not reviewed: <error>`.
- If no PR has errors, the message ends after the last PR block: there is
  nothing to ask.
- Leave out: a TLDR, headings, process narration, offers of Approve or Request
  changes, offers of extra work.

## The answer

- `All` or `Only: <numbers>`: go to [commenting.md](commenting.md).
- `None`: post nothing. The run ends.
