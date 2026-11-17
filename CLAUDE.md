# CLAUDE.md

## Context hygiene: suggest `/clear`

Remind the user to run `/clear` when starting fresh would help more than carrying the conversation forward. Suggest it in one short line at the end of a reply (never run it yourself, never nag), for example:

> 💡 This task is done. Consider `/clear` before starting the next one.

Suggest it when:
- A task is finished (committed, pushed, or confirmed working) and the user moves to an unrelated topic.
- The conversation is long and earlier context (big file dumps, logs, abandoned approaches) no longer matters.
- Work switches between distinct areas of the repo, e.g. from the e-paper renderer (`layout_renderer.py`, `epd_dashboard.py`) to `aws_lambda/` or `infra/`.
- Several attempts at a fix went in circles and a clean restart with a short summary would help.

Don't suggest it when:
- The task is still in progress, or the next request builds on the current context.
- It was already suggested recently and the user carried on.

When suggesting it during unfinished work, offer a 2–3 line summary the user can paste into the fresh session.
