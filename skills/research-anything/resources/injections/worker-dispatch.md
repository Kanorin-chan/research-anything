---
moment: worker-dispatch
level: remind
placeholders: [task, worker, identity]
---
# Before you dispatch a worker
You ({identity}) are about to hand this task to {worker}: {task}
- One fresh worker per task. Do not send a new task into an old worker's session.
- Reusing a session is allowed only when the same worker is continuing its own task.
- Past failure: a new task was sent into the `Subagent_TESTSET` session under a new name, so the worker kept the old task's assumptions.
- Give the worker the real data path and the success criterion in numbers. Do not hand it the example data.
- The native sub-agent tool is free only on your own model: no `model=` override. Another model is another agent and needs a grant naming it.
- Never list model catalogues (`tools.opencode.models`, `opencode models`, provider lists) to pick a worker model. Ask the user.
- Past failure: Qwen listed 139 models, granted itself a paid one with its own sentence, and ran it via `subagent model=`.
