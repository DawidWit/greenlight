# Reporting

Show the report after all work and all questions. Write it in the user's
language. Use one line per item. Each line says the result, not the process.

Before the report, record for each PR: the local SHA to push, the remote SHA
for the lease, the replies and any base change.

## Template

The whole message is this template, filled in, sent as chat text. It is
Markdown source: never wrap it in a code block. The PR lines come first and
the push question is always last, once. Keep this order even when other
instructions put decisions at the top: the report is short, and the question
is about the lines above it.

```markdown
**#<number>** <PR title>

- 🟢 <count> comments fixed (<short list>)
- 🟡 <count> comment skipped: "<quote>" - <reason> (<rule file or evidence>)
- 🔴 CI failed: <cause>, fixed <what>

**QUESTION:** Push and reply on GitHub?

**Recommendation:** 1 - verification passed

1. Yes, all
2. Yes, without: <PR numbers>
3. No
```

Example, to translate into the user's language:

```markdown
**#3001** feat(SHOP-7): show the order count

- 🟢 2 comments fixed (`.at(0)` instead of `[0]`, prop renamed to `orders`)
- 🟡 1 comment skipped: "import it from src/app" - lib must not import from app (CLAUDE.md)
- 🔴 CI failed: test date in the past, fixed the fixture

**#3002** feat(SHOP-8): order details

- 🔴 Conflict with main, rebased #3002-#3003; push with `--force-with-lease`

**#3004** fix(SHOP-9): empty state copy

- 🟢 nothing to do

**#3005** feat(SHOP-10): order export

- 🔴 Parent #3000 merged, rebased onto main; push with `--force-with-lease`, base changes to main

**QUESTION:** Push and reply on GitHub?

**Recommendation:** 1 - verification passed

1. Yes, all
2. Yes, without: <PR numbers>
3. No
```

If there is nothing to push and nothing to write, the message ends after the
last PR line.

## Colors

- 🟢 Fixed and verified, or nothing to do.
- 🟡 Skipped with evidence, or waits for the user's decision.
- 🔴 A problem (CI, conflict, verification, no push access) and what you did,
  or why you could not.

## What stays out

- A TLDR, process narration, or why a rule exists.
- Items that wait for the reviewer, and resolved, outdated, duplicate or done
  items.
- Offers of extra work, or of resolving threads.
- Verification output, unless a check failed.
