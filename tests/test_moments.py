"""Task 7: injections wired into the gate moments (status, review, return-baton, advance, graduate)."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ra_common as rc  # noqa: E402

GATE = ROOT / "scripts" / "ra_gate.py"
HARNESS = ROOT / "scripts" / "ra_context_harness.py"
HARNESS_VARS = ("OPENCODE", "OPENCODE_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                "CODEX_HOME", "CODEX_SANDBOX", "CODEX_SESSION_ID", "ANTIGRAVITY_CLI", "GEMINI_CLI", "XDG_DATA_HOME")

REVIEW_BODY = (
    "# Review 1\n"
    "DECISION: pin_distance: KEEP\n"
    "LESSON: pin distance sits near 0.31 because the pins are noisy at long range\n"
    "NEXT: run one more pin_distance round with the median filter\n"
    "Scores so far reach 0.31 against the 0.8 target.\n"
)
REVIEW_ANSWERS = (
    "\n## Answers\n"
    "1. Worth one more round: 0.31 is 0.49 short of 0.8, and the median filter should add about 0.1 per round.\n"
    "2. Nothing was tried before: the graveyard is empty, so this is the first attempt at this family.\n"
    "3. I stop if the best stays under 0.4 after the next two rounds.\n"
)
HANDOVER_ANSWERS = (
    "\n## Handover answers\n"
    "1. Yes, I ran it on research/data/real_scan.csv, the 40-row real capture.\n"
    "2. Nothing is made up; every row came from the real capture, none from the example.\n"
    "3. It is not a renamed method; it is a new median filter over the pin readings.\n"
    "4. It works as intended; I checked it against the hand-measured distances in the log.\n"
    "5. A user who has never seen the code would find a filtered distance reasonable.\n"
    "6. Factors: window size 5 (noise), median (outliers), no smoothing (keeps edges).\n"
    "7. Sure about the filter result; guessing the window size generalises to other rigs.\n"
)
GRAD_ANSWERS = (
    "1. It works on research/data/heldout.csv, which it never saw; the score was 0.84.\n"
    "2. Nothing was faked; I grepped for hardcoded case values and found none.\n"
    "3. The user would first notice the distance shown in millimetres, not pixels.\n"
    "4. Still a guess: behaviour on a different camera; it would degrade to the old score.\n"
)


def env_for(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    home = str(tmp_path / "home")
    env.update({"USERPROFILE": home, "HOME": home, "PYTHONUTF8": "1"})
    env.update(extra)
    return env


def run(script, args, env, cwd):
    p = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, env=env, cwd=str(cwd))
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def make_ws(tmp_path, env):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert run(GATE, ["init", "--workspace", str(ws)], env, tmp_path)[0] == 0
    return ws


def edit_state(ws, fn):
    p = ws / "research" / ".ra_state.json"
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    fn(data)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def board(ws, scores=(0.2, 0.25, 0.31), stage="STAGE_3_SANDBOX_PROTOTYPE"):
    def fn(d):
        d["active_hypothesis"] = "H001"
        d["current_stage"] = stage
        d["stop_rules"] = {"pins": {"hypothesis": "H001", "metric": "pass_rate", "target": 0.8, "min_gain": 0.02}}
        d["scoreboard"] = {"H001": {"approaches": {"pin_distance": {
            "status": "RACING", "rounds": [{"score": s, "unseen": False} for s in scores]}}}}
    edit_state(ws, fn)


def review(ws, env, tmp_path, body):
    f = ws / "research" / "reviews" / "REVIEW_1.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return run(GATE, ["review", "--workspace", str(ws), "--file", "research/reviews/REVIEW_1.md"], env, tmp_path)


def test_review_needs_answers(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    board(ws)
    code, out, err = review(ws, env, tmp_path, REVIEW_BODY)
    assert code == 2 and "## Answers" in err
    assert "Review meeting" in err  # the rendered template rides in the block message
    code, out, err = review(ws, env, tmp_path, REVIEW_BODY + "\n## Answers\n1. yes\n2. ok\n3. done\n")
    assert code == 2 and "bare 'yes'" in err
    code, out, err = review(ws, env, tmp_path, REVIEW_BODY + REVIEW_ANSWERS)
    assert code == 0, out + err
    assert "REVIEW #1 ACCEPTED" in out


def test_review_facts_filled(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    board(ws)
    code, out, err = review(ws, env, tmp_path, REVIEW_BODY)
    assert code == 2
    block = err
    assert "`pin_distance` has had 3 rounds" in block and "Best result so far: 0.31" in block and "Target: 0.8" in block
    assert "{unknown" not in block and "none yet" in block


def test_graveyard_facts_from_report_and_scoreboard_only(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    board(ws)
    grave = ws / "research" / "graveyard" / "H000"
    grave.mkdir(parents=True)
    (grave / "REPORT.md").write_text(
        "# Report H000\n- **Final Verdict**: `FALSIFIED`\n"
        "- **Exact Root Cause (Why it worked or why it failed)**:\n  Template matching breaks under rotation.\n"
        "- **Next Move**: manager prose that must not appear\n", encoding="utf-8")
    edit_state(ws, lambda d: (d["stop_rules"].update({"old": {"hypothesis": "H000", "metric": "m", "target": 0.8, "min_gain": 0.01}}),
                              d["scoreboard"].update({"H000": {"approaches": {"template_match": {
                                  "status": "DROPPED", "rounds": [{"score": 0.4}, {"score": 0.55}]}}}})))
    facts = rc.graveyard_facts(ws)
    assert facts == "template_match: best 0.55, FALSIFIED, Template matching breaks under rotation."
    assert "manager prose" not in facts
    assert rc.graveyard_facts(tmp_path / "nowhere") == "none yet"
    code, out, err = review(ws, env, tmp_path, REVIEW_BODY)
    assert "template_match: best 0.55, FALSIFIED" in err


def fork_one(ws, env, tmp_path):
    assert run(HARNESS, ["create", "--workspace", str(ws), "--id", "base", "--tier", "workflow_slice",
                         "--summary", "shared context"], env, tmp_path)[0] == 0
    code, out, err = run(HARNESS, ["fork", "--workspace", str(ws), "--subagent", "Subagent_A", "--snapshots", "base",
                                   "--task", "filter the pins"], env, tmp_path)
    assert code == 0, out + err


def test_return_baton_needs_handover_answers(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    ws = make_ws(tmp_path, env)
    fork_one(ws, env, tmp_path)
    report = ws / "research" / "context_snapshots" / "reports" / "REPORT_Subagent_A.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# Report\nI filtered the pins and the result looks fine to me.\n", encoding="utf-8")
    args = ["return-baton", "--workspace", str(ws), "--subagent", "Subagent_A", "--status", "COMPLETED"]
    code, out, err = run(HARNESS, args, env, tmp_path)
    assert code == 1 and "Handover answers" in err and "Worker handover" in err
    reg = json.loads((ws / "research" / "context_snapshots" / "SNAPSHOT_REGISTRY.json").read_text(encoding="utf-8"))
    assert "Subagent_A" in reg["outstanding_forks"]  # nothing was returned
    report.write_text("# Report\nDone.\n\n## Handover answers\n1. yes\n2. ok\n", encoding="utf-8")
    code, out, err = run(HARNESS, args, env, tmp_path)
    assert code == 1 and "question 1" in err
    report.write_text("# Report\nDone.\n" + HANDOVER_ANSWERS, encoding="utf-8")
    code, out, err = run(HARNESS, args, env, tmp_path)
    assert code == 0, out + err
    assert "BATON RETURNED" in out


def test_return_baton_failed_status_needs_no_answers(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    ws = make_ws(tmp_path, env)
    fork_one(ws, env, tmp_path)
    code, out, err = run(HARNESS, ["return-baton", "--workspace", str(ws), "--subagent", "Subagent_A",
                                   "--status", "FAILED", "--summary", "ran out of context"], env, tmp_path)
    assert code == 0, out + err


def test_graduate_needs_answers(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    board(ws, stage="STAGE_7_GRADUATION_REVIEW")
    edit_state(ws, lambda d: d.update({"log_audit_passed": True, "visual_audit_passed": True, "cheese_audit_passed": True}))
    base = ["graduate", "--workspace", str(ws), "--user-approved", "looks good, ship it"]
    code, out, err = run(GATE, base, env, tmp_path)
    assert code == 1 and "--answers" in err and "Before graduation" in out
    bad = tmp_path / "bad.md"
    bad.write_text("1. yes\n2. ok\n3. done\n4. sure\n", encoding="utf-8")
    code, out, err = run(GATE, base + ["--answers", str(bad)], env, tmp_path)
    assert code == 1 and "question 1" in err
    good = tmp_path / "before-graduation_1.md"
    good.write_text(GRAD_ANSWERS, encoding="utf-8")
    code, out, err = run(GATE, base + ["--answers", str(good)], env, tmp_path)
    assert code == 0, out + err
    assert (ws / "research" / "library" / "GRADUATED_H001.md").is_file()


def test_allow_agent_needs_answers(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    base = ["allow-agent", "--workspace", str(ws), "--agent", "opencode:x/y",
            "--quote", "use opencode y as a worker please", "--source", "chat"]
    code, out, err = run(GATE, base, env, tmp_path)
    assert code == 1 and "--answers" in err and "Before using another agent" in out and "opencode:x/y" in out
    assert not (ws / "research" / "AGENT_PERMISSIONS.json").exists()
    ans = tmp_path / "a.md"
    ans.write_text("1. yes\n2. ok\n3. done\n", encoding="utf-8")
    assert run(GATE, base + ["--answers", str(ans)], env, tmp_path)[0] == 1
    ans.write_text(
        "1. The user said: use opencode as a worker please, in chat today.\n"
        "2. I cannot run a second model myself for the cold review.\n"
        "3. It may read research/ and write only research/sandbox/H001/.\n", encoding="utf-8")
    assert run(GATE, base + ["--answers", str(ans)], env, tmp_path)[0] == 0
    assert rc.is_agent_allowed(ws, "opencode:x/y")


def test_status_shows_identity(tmp_path):
    env = env_for(tmp_path, CLAUDECODE="1")
    ws = make_ws(tmp_path, env)
    code, out, err = run(GATE, ["status", "--workspace", str(ws)], env, tmp_path)
    assert code == 0, out + err
    assert "# Session start" in out and "You are: claude-code:" in out
    assert "{unknown" not in out
    code, out, err = run(GATE, ["resume", "--workspace", str(ws)], env, tmp_path)
    assert code == 0 and "You are: claude-code:" in out


def test_advance_stage2_to_3_prints_before_build(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    board(ws, scores=(), stage="STAGE_2_HYPOTHESIS_FORMULATION")
    (ws / "research" / "WORKFLOW_MAP.md").write_text("# Map\nfilled in\n", encoding="utf-8")
    rep = ws / "research" / "hypotheses" / "H001" / "REPORT.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text("# H001\n## 3. Option Sweep\nfilled in\n", encoding="utf-8")
    code, out, err = run(GATE, ["advance", "--workspace", str(ws)], env, tmp_path)
    assert code == 0, out + err
    assert "# Before build" in out and "`H001`" in out


def test_hook_session_start_and_review_call(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    board(ws)
    hooks = ROOT / "scripts" / "ra_hooks.py"
    payload = json.dumps({"hook_event_name": "SessionStart", "source": "startup", "cwd": str(ws), "model": "claude-opus-5-5",
                          "session_id": "s1"})
    p = subprocess.run([sys.executable, "-I", str(hooks), "session-start"], input=payload.encode(), capture_output=True,
                       env=env, cwd=str(ws))
    assert p.returncode == 0, p.stderr
    text = json.loads(p.stdout.decode())["hookSpecificOutput"]["additionalContext"]
    assert "You are: claude-code:claude-opus-5-5" in text
    sys.path.insert(0, str(ROOT / "scripts"))
    import ra_hooks
    call = ra_hooks.review_call(ws, None)
    assert "`pin_distance` has had 3 rounds" in call and "Target: 0.8" in call and "DECISION:" in call


def _emitted(capfd):
    return json.loads(capfd.readouterr().out)["hookSpecificOutput"]["additionalContext"]


def test_long_board_keeps_reminder_identity_and_review_command(tmp_path, monkeypatch, capfd):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    board(ws)
    import ra_hooks
    monkeypatch.setattr(ra_hooks, "full_board", lambda w, reason=None: "BOARDLINE " * 3000)
    ra_hooks.on_session_start(ws, {"source": "startup", "model": "claude-opus-5-5", "session_id": "s1"})
    text = _emitted(capfd)
    assert len(text) <= ra_hooks.CONTEXT_CAP
    assert "You are: claude-code:claude-opus-5-5" in text and "Reminders before you touch anything" in text
    assert "board truncated" in text
    ra_hooks.emit_context("UserPromptSubmit", ra_hooks.review_call(ws, None))
    text = _emitted(capfd)
    assert "review --file research/reviews/REVIEW_1.md" in text and "Target: 0.8" in text and "board truncated" in text


def test_refusals_are_recoverable_in_one_try(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    ws = make_ws(tmp_path, env)
    fork_one(ws, env, tmp_path)
    code, out, err = run(HARNESS, ["return-baton", "--workspace", str(ws), "--subagent", "Subagent_A", "--status", "COMPLETED",
                                   "--summary", "done"], env, tmp_path)
    assert code == 1
    rp = "research/context_snapshots/reports/REPORT_Subagent_A.md"
    assert "## Handover answers" in err and "the worker `Subagent_A`" in err and "written by the manager" in err
    assert f"return-baton --workspace . --subagent Subagent_A --status COMPLETED --report-file {rp}" in err
    board(ws, stage="STAGE_7_GRADUATION_REVIEW")
    code, out, err = run(GATE, ["graduate", "--workspace", str(ws), "--user-approved", "looks good, ship it"], env, tmp_path)
    assert "research/answers/before-graduation_1.md" in err and "graduate --workspace . --user-approved" in err and "--answers" in err
    code, out, err = run(GATE, ["allow-agent", "--workspace", str(ws), "--agent", "opencode:x/y", "--quote",
                                "use opencode y as a worker please", "--source", "chat"], env, tmp_path)
    assert "research/answers/before-other-agent_1.md" in err and "allow-agent --workspace . --agent opencode:x/y" in err


def test_return_baton_then_shows_review_template_not_old_block(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    ws = make_ws(tmp_path, env)
    board(ws)
    fork_one(ws, env, tmp_path)
    report = ws / "research" / "context_snapshots" / "reports" / "REPORT_Subagent_A.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# Report\nok\n" + HANDOVER_ANSWERS, encoding="utf-8")
    code, out, err = run(HARNESS, ["return-baton", "--workspace", str(ws), "--subagent", "Subagent_A", "--status", "COMPLETED"],
                         env, tmp_path)
    assert code == 0, out + err
    assert "`pin_distance` has had 3 rounds" in out and "## Answers" in out
    assert "Are we closer to the target" not in out


def test_review_template_rendered_once_for_many_approaches(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    board(ws)
    edit_state(ws, lambda d: d["scoreboard"]["H001"]["approaches"].update(
        {"template_match": {"status": "RACING", "rounds": [{"score": 0.1}]}}))
    text = rc.render_review_meeting(ws)
    assert text.count("# Review meeting") == 1 and text.count("The graveyard says") == 1
    assert "`pin_distance`: 3 rounds, best 0.31" in text and "`template_match`: 1 rounds, best 0.1" in text


def test_fork_native_line_always_printed_with_cli_after_grant(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    ws = make_ws(tmp_path, env)
    rc.grant_agent(ws, "opencode:llamacpp/qwen3.8-flash-next", "use opencode qwen as one of your subagent", "chat")
    fork_one(ws, env, tmp_path)
    code, out, err = run(HARNESS, ["fork", "--workspace", str(ws), "--subagent", "Subagent_B", "--snapshots", "base",
                                   "--task", "other", "--parallel"], env, tmp_path)
    assert code == 0, out + err
    assert '`subagent` tool with agent="general", description="Subagent_B", prompt="Read ' in out
    assert out.index('`subagent` tool') < out.index("opencode run")
