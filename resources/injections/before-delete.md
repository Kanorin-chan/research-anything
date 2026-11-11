---
moment: before-delete
level: answer
placeholders: [targets, workspace]
---
# Before delete
You are about to delete: {targets}
Past failure: rm was denied, so the agent ran `mv x ../x.bak`. That is a delete; use `ra_gate.py remove`.
Answer in research/answers/before-delete_<n>.md (<n> = this occurrence's sequence number: 1, 2, ...) before running `ra_gate.py remove`. The one file holds every numbered answer, 1. to 4:
1. Is every path inside {workspace}/research/sandbox, or a file you created this session? List each path, workspace-relative (e.g. research/sandbox/x), and say which.
2. Does anything depend on it (imports, configs, running processes, other files)? How did you check?
3. Is any of it the user's own data or work? If you are not certain, treat it as yes and stop.
4. Can it be recovered if you are wrong? How (trash, git, backup)?
