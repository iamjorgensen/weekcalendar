# CLAUDE.md

## Suggest `/clear`

End a reply with a one-line `/clear` suggestion (never run it) when:
- a task is done and the user moves to something unrelated,
- the conversation is long and earlier context no longer matters,
- work switches repo areas (e.g. renderer → `aws_lambda/` or `infra/`),
- fix attempts are going in circles.

Skip it mid-task, when the next step builds on current context, or if recently suggested. If work is unfinished, include a 2–3 line summary to paste into the fresh session.
