# Commenting

## Comment text

Each comment is short, in plain technical English: what is wrong, why, and the
fix when it is obvious. One or two sentences. No greeting, no praise, no "nit".
Follow the repository's rules about review comments when it has them.

## Where each comment goes

Before the second question, check every picked comment against the hunks of
`git diff origin/<baseRefName>...<headRefOid>` for its file:

- A new or unchanged line inside a hunk: inline, `"side": "RIGHT"`, with the
  line number in the new file.
- A deleted line inside a hunk: inline, `"side": "LEFT"`, with the line number
  in the old file.
- A range of lines inside one hunk: add `start_line` (and `start_side`) for
  the first line, `line` for the last.
- Any line outside the hunks: it cannot be inline, because GitHub rejects the
  whole review. It goes in the review body as `<path>:<line> - <text>`.

## The second question

Show the exact texts of the picked errors, sent as chat text. It is Markdown
source: never wrap it in a code block. Keep the numbers from the list, and mark
each comment that goes in the review body.

```markdown
**Comments to post**

**#<number>**

<n>. `<path>:<line>`

> <exact comment text>

<n>. `<path>:<line>` (in the review body, outside the diff)

> <exact comment text>

**QUESTION:** Post these comments?

**Recommendation:** 1 - the texts match the list

1. Yes
2. Change: <number and what to change>
3. No
```

- `Yes`: publish below.
- `Change`: rewrite that comment, show all texts again, ask again.
- `No`: post nothing.

## Publish

Only after a yes to the second question. Always send the review with
event=COMMENT: one review per PR with all its picked comments.

1. Check that the PR head is still the `headRefOid` you reviewed
   (`gh pr view <number> --repo <owner/repo> --json headRefOid`). If it moved,
   do not post to that PR: review it again and show its list again, with the
   same numbering rules. Post the other PRs.
2. Write the review to a JSON file and send it:

   ```json
   {
     "commit_id": "<headRefOid>",
     "event": "COMMENT",
     "body": "<comments outside the diff, one per line, or empty>",
     "comments": [
       { "path": "<path>", "line": <line>, "side": "RIGHT", "body": "<text>" },
       { "path": "<path>", "line": <old line>, "side": "LEFT", "body": "<text>" }
     ]
   }
   ```

   ```text
   gh api -X POST repos/<owner>/<repo>/pulls/<number>/reviews --input <file>
   ```

3. A rejected review (for example HTTP 422, a line GitHub does not accept)
   posts nothing for that PR. Report the error with the PR number and stop
   for that PR. Do not retry with changed lines without showing the texts
   again.
4. After posting, show one line per PR, for example
   `#270: 2 comments posted - <review url>`, plus every error.

## Never

Never approve, request changes, merge or close pull requests, resolve threads,
request reviews, push to the author's branch, or re-run CI. When the user asks
for Approve or Request changes, answer in one line that it is their click, with
the PR link, and post only the comments.
