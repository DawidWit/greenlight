# Rules Check

Check the plan against the rules of the target repository before you write code. In the "From existing changes" mode, check the diff instead of the plan.

## Find the rules

Read every file that tells how code in this repository must be written:

- `CLAUDE.md` and `AGENTS.md` at the root and in the directories the change touches
- `.claude/rules/*.md`, `.cursor/rules/`, `.github/copilot-instructions.md`
- `CONTRIBUTING.md`, `docs/adr/`, style or standards documents
- Every file these documents point to

Configured tooling (linter, formatter, type checker) enforces its own rules. Do not check those by hand; verification runs them.

If you find none of these files, write "no rules found" in the plan and in the publish summary, and continue. Do not invent rules.

## Check and correct

1. Take each planned change: file placement, names, types, patterns, dependencies, commands, tests.
2. Compare it with every rule that applies.
3. When a change breaks a rule, change the plan so that it obeys the rule. Do not ask the user first. Record the rule and the change in the "Rules check" section of the plan file.
4. Repeat until no planned change breaks a rule.

In the "From existing changes" mode, correct the code the same way and record each correction for the publish summary.

## When a rule and the requirement collide

When you cannot obey a rule and also deliver what the ticket or the user asked for, do not choose. Ask through the Human Decision Gate in SKILL.md. Continue with the parts the conflict does not touch.
