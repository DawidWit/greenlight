# Asking

## Look first

Before you ask, read the ticket, the user's description, the code the task touches and the repository rules. Ask only what none of them answers.

Getting the ticket:

- If the user gives a ticket key or link and you have a tool for that tracker (for example a Jira MCP server or `gh`), read the ticket with it.
- If you have no such tool, ask the user to paste the ticket text.
- A ticket is optional. Without one, the user's description is the source.
- From existing changes with no ticket and no description: ask one short question about what the change must do. Do not take the goal from the diff, and do not ask for a ticket key.

## Who gets the question

Sort each open point before you ask it:

- **How to build it** (code, structure, tests, tools, trade-offs between implementations): ask the user.
- **What it must do** (behavior, copy, permissions, which data, edge cases the ticket does not settle): write it for the PO.

## A question for the user

Ask one question at a time, through the Human Decision Gate in SKILL.md. The question is:

- in the user's language
- one sentence, in plain technical words
- the shortest form that keeps the meaning: remove each word whose removal does not change the answer
- without a preface, a summary of the task, or a list of your assumptions

Bad: `Before I start I want to confirm a few things: 1) which roles should see the button, 2) whether to export only the current page, 3) which columns... If you accept my proposals, reply "ok".`

Good: `QUESTION: Export only the current page or all filtered orders?`

Ask the next question only after the answer to this one.

## A message for the PO

Collect the "what it must do" points into one message the user forwards to the PO. Write it in the user's language and in plain words, with no code names:

Send it as chat text, never in a code block. Markdown source:

```markdown
**MESSAGE FOR THE PO**

> <one sentence: what we are building>
>
> 1. <question>
> 2. <question, only if needed - at most 3>
>
> <one sentence: what waits for the answer>
```

Then continue without the answer:

1. Move the part that depends on the answer into its own slice with status `waiting for PO` (see [slicing.md](slicing.md)).
2. Record the questions in the plan file under "Waiting for PO".
3. Build the rest. Do not build the waiting part on a guess and do not prepare code for possible answers.

When the user brings the PO's answer, read the plan file and continue with the waiting slice.
