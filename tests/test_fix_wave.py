"""Final-review fix wave (v1.6): one section per finding in final-fix-findings.md."""
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ra_common as rc  # noqa: E402
import ra_forge  # noqa: E402
import ra_hooks  # noqa: E402

GATE = ROOT / "scripts" / "ra_gate.py"
HOOKS = ROOT / "scripts" / "ra_hooks.py"
HARNESS = ROOT / "scripts" / "ra_context_harness.py"
FORGE = ROOT / "scripts" / "ra_forge.py"
HARNESS_VARS = ("OPENCODE", "OPENCODE_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                "CODEX_HOME", "CODEX_SANDBOX", "CODEX_SESSION_ID", "ANTIGRAVITY_CLI", "GEMINI_CLI", "XDG_DATA_HOME",
                "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR")
WIN = os.name == "nt"
REVIEW_FOCUS_PASS = [
    "git status", "grep -rn rm src/", "cat claude_notes.md", "python claude_shim.py", 'echo "rm -rf is dangerous"',
    "cat <<'EOF'\nrm -rf /\nEOF", "npm uninstall x",
]
DELETE_ANSWERS = (
    "1. Every path is under research/sandbox and I created it this session: {paths}.\n"
    "2. Nothing depends on it; grep -rn over the repo found no imports or config references.\n"
    "3. None of it is the user's own data; it is scratch output from my own test run.\n"
    "4. Recoverable: remove moves it to research/.trash with a manifest.\n"
)
OTHER_AGENT_ANSWERS = (
    "1. The user said in chat today: use that agent as one of your workers ({n}).\n"
    "2. The task needs a second model for the cold review; I cannot do that myself.\n"
    "3. It may read research/ and write only research/sandbox/H001/.\n"
)
HANDOVER = (
    "1. Yes, I ran it on research/data/real_scan.csv, the 40-row real capture.\n"
    "2. Nothing is made up; every row came from the real capture, none from the example.\n"
    "3. It is not a renamed method; it is a new median filter over the pin readings.\n"
    "4. It works as intended; I checked it against the hand-measured distances in the log.\n"
    "5. A user who has never seen the code would find a filtered distance reasonable.\n"
    "6. Factors: window size 5 (noise), median (outliers), no smoothing (keeps edges).\n"
    "7. Sure about the filter result; guessing the window size generalises to other rigs.\n"
)
REVIEW_BODY = (
    "# Review 1\n"
    "DECISION: pin_distance: KEEP\n"
    "LESSON: pin distance sits near 0.31 because the pins are noisy at long range\n"
    "NEXT: run one more pin_distance round with the median filter\n"
    "Scores so far reach 0.31 against the 0.8 target.\n"
    "\n## Answers\n"
    "1. Worth one more round: 0.31 is 0.49 short of 0.8, and the median filter should add about 0.1 per round.\n"
    "2. Nothing was tried before: the graveyard is empty, so this is the first attempt at this family.\n"
    "3. I stop if the best stays under 0.4 after the next two rounds.\n"
)


def env_for(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    home = str(tmp_path / "home")
    env.update({"USERPROFILE": home, "HOME": home, "PYTHONUTF8": "1"})
    env.update(extra)
    return env


def run(script, args, env, cwd, stdin=None):
    p = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, env=env, cwd=str(cwd), input=stdin)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    assert run(GATE, ["init", "--workspace", str(w)], env_for(tmp_path), tmp_path)[0] == 0
    return w


def kinds(cmd):
    return {k for k, _ in ra_hooks.shell_safety(cmd)}


def hook(tmp_path, w, tool, command, **extra):
    payload = {"cwd": str(w), "tool_name": tool, "tool_input": {"command": command}, "session_id": "s1", **extra}
    code, out, err = run(HOOKS, ["pre-tool"], env_for(tmp_path), tmp_path, json.dumps(payload).encode())
    return code, err


# ---------------------------------------------------------------- 1. command prefixes


PREFIX_BLOCKS = [
    ("timeout 60 rm -rf research/sandbox", "delete"),
    ("timeout 300 claude -p hi", "agent-launch"),
    ("nice rm -rf x", "delete"),
    ("nice -n 10 rm x", "delete"),
    ("nice -5 rm x", "delete"),
    ("ionice -c 3 -n 7 rm x", "delete"),
    ("ionice -c3 rm x", "delete"),
    ("stdbuf -o0 rm x", "delete"),
    ("stdbuf -o L -e 0 rm x", "delete"),
    ("stdbuf --output=L rm x", "delete"),
    ("builtin rm x", "delete"),
    ("env -i rm x", "delete"),
    ("env -u PATH rm x", "delete"),
    ("env FOO=1 BAR=2 rm x", "delete"),
    ("env -i FOO=1 claude -p x", "agent-launch"),
    ("env -S 'rm -rf x'", "delete"),
    ("sudo -u x rm y", "delete"),
    ("sudo -E -u root rm y", "delete"),
    ("sudo -Eu root rm y", "delete"),
    ("sudo -g g -h h -p pw rm y", "delete"),
    ("sudo --user=root rm y", "delete"),
    ("nohup rm x", "delete"),
    ("nohup codex exec y", "agent-launch"),
    ("time rm x", "delete"),
    ("time -p rm x", "delete"),
    ("command rm x", "delete"),
    ("command -p rm x", "delete"),
    ("exec rm x", "delete"),
    ("timeout -s KILL 5 rm x", "delete"),
    ("timeout --signal=KILL -k 2 5 rm x", "delete"),
    ("sudo timeout 5 nice -n 2 rm x", "delete"),
    ("/usr/bin/timeout 5 rm x", "delete"),
    ("cd x && timeout 9 rm y", "delete"),
    ("(timeout 5 rm x)", "delete"),
    ("( rm x )", "delete"),
    ("(sudo rm x)", "delete"),
    ("{ nice rm x; }", "delete"),
]

PREFIX_PASSES = [
    "timeout 60 python -m pytest tests -q", "nice -n 10 make", "env", "env | grep CLAUDE", "sudo -l", "timeout /t 5",
    "time python bench.py", "nohup python server.py", "command -v python", "stdbuf -oL tail -f x.log",
    "env -u FOO git status", "timeout 30 npm run build",
]


@pytest.mark.parametrize("cmd,kind", PREFIX_BLOCKS)
def test_prefix_blocks(cmd, kind):
    assert kind in kinds(cmd), (cmd, ra_hooks.shell_safety(cmd))


@pytest.mark.parametrize("cmd", PREFIX_PASSES)
def test_prefix_passes(cmd):
    assert ra_hooks.shell_safety(cmd) == [], cmd


def test_command_v_is_still_a_lookup():
    assert kinds("command -v codex") == {"agent-lookup"}
    assert kinds("command -V claude") == {"agent-lookup"}


def test_hook_blocks_prefixed_delete(tmp_path, ws):
    code, err = hook(tmp_path, ws, "Bash", "timeout 60 rm -rf research/sandbox")
    assert code == 2 and "Before delete" in err


# ---------------------------------------------------------------- 2. git checkout . / git rm


GIT_BLOCKS = [
    "git checkout .", "git checkout :/", "git checkout '*'", "git checkout '*.py'", "git checkout HEAD -- src/a.py",
    "git checkout -- .", "git checkout ./src", "git checkout -f", "git checkout --force main", "git rm x",
    "git rm -r dir", "git -C repo rm x", "git restore .", "git restore --staged --worktree x", "git restore -SW x",
    "git clean -fd", "git reset --hard", "git switch --discard-changes main", "git switch -f main",
]

GIT_PASSES = [
    "git checkout main", "git checkout -b feat/x", "git checkout feature/v1.2", "git rm --cached x",
    "git rm -r --cached dir", "git rm -n x", "git restore --staged a.py", "git restore -S a.py", "git status",
    "git switch main", "git clean -n",
]


@pytest.mark.parametrize("cmd", GIT_BLOCKS)
def test_git_blocks(cmd):
    assert "delete" in kinds(cmd), (cmd, ra_hooks.shell_safety(cmd))


@pytest.mark.parametrize("cmd", GIT_PASSES)
def test_git_passes(cmd):
    assert ra_hooks.shell_safety(cmd) == [], cmd


# ---------------------------------------------------------------- 3. no tree walk


def test_classify_does_not_walk(ws, monkeypatch):
    big = ws / "research" / "sandbox" / "big"
    (big / "deep").mkdir(parents=True)
    (big / "deep" / "f.txt").write_text("x")
    (ws / "research" / "hypotheses" / "H1" / "sub").mkdir(parents=True)
    (ws / "research" / "hypotheses" / "H1" / "REPORT.md").write_text("keep")

    def boom(*a, **k):
        raise AssertionError("os.walk used")

    monkeypatch.setattr(rc.os, "walk", boom)
    assert rc.classify_delete_path(ws, str(big))[0] == "research"
    assert rc.classify_delete_path(ws, str(ws / "research" / "hypotheses"))[0] == "protected"
    assert rc.classify_delete_path(ws, str(ws / "research" / "hypotheses" / "H1"))[0] == "protected"
    assert rc.classify_delete_path(ws, str(ws / "research" / "hypotheses" / "H1" / "sub"))[0] == "research"
    (ws / "research" / "hypotheses" / "H2").mkdir()
    assert rc.classify_delete_path(ws, str(ws / "research" / "hypotheses" / "H2"))[0] == "research"


def test_classify_big_sandbox_is_fast(ws):
    big = ws / "research" / "sandbox" / "big"
    for i in range(40):
        d = big / f"d{i}"
        d.mkdir(parents=True)
        for j in range(50):
            (d / f"f{j}.txt").write_text("")
    t = time.time()
    assert rc.classify_delete_path(ws, str(big))[0] == "research"
    assert time.time() - t < 0.2


def test_git_delete_does_not_name_the_workspace(ws):
    assert ra_hooks._delete_targets(ws, "", str(ws)) == "(targets not readable from the command)"


def test_hook_skips_child_check(ws, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("child check in the hook")

    monkeypatch.setattr(rc, "_has_protected_child", boom)
    shown = ra_hooks._delete_targets(ws, str(ws / "research" / "hypotheses"), str(ws))
    assert "research/hypotheses" in shown and "(research)" in shown


# ---------------------------------------------------------------- 4. Claude Code worker transcripts


def _line(obj):
    return json.dumps(obj) + "\n"


def claude_tree(tmp_path, sid, main_model="claude-opus-5-5", worker_model="claude-haiku-5", worker_newer=True):
    proj = tmp_path / "home" / ".claude" / "projects" / "C--ws"
    proj.mkdir(parents=True)
    main = proj / f"{sid}.jsonl"
    main.write_text(_line({"type": "assistant", "message": {"model": main_model}}), encoding="utf-8")
    sub = proj / sid / "subagents"
    sub.mkdir(parents=True)
    worker = sub / "agent-a1b2c3d4e5f6a7b8c.jsonl"
    worker.write_text(_line({"type": "assistant", "agentId": "a1b2c3d4e5f6a7b8c", "message": {"model": worker_model}}),
                      encoding="utf-8")
    now = time.time()
    os.utime(main, (now - (60 if worker_newer else 0), now - (60 if worker_newer else 0)))
    os.utime(worker, (now - (0 if worker_newer else 60), now - (0 if worker_newer else 60)))
    return main, worker


SID = "11111111-2222-3333-4444-555555555555"


def cc_env(tmp_path):
    home = str(tmp_path / "home")
    return {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": SID, "USERPROFILE": home, "HOME": home}


def test_claude_worker_transcript_newest_is_caller(tmp_path):
    claude_tree(tmp_path, SID, worker_newer=True)
    r = rc.resolve_identity(cc_env(tmp_path), {})
    assert r["agent"] == "claude-code:claude-haiku-5" and r["is_subagent"] is True


def test_claude_main_transcript_newest_is_manager(tmp_path):
    claude_tree(tmp_path, SID, worker_newer=False)
    r = rc.resolve_identity(cc_env(tmp_path), {})
    assert r["agent"] == "claude-code:claude-opus-5-5" and r["is_subagent"] is False


def test_claude_payload_agent_id_picks_its_transcript(tmp_path):
    main, worker = claude_tree(tmp_path, SID, worker_newer=False)
    r = rc.resolve_identity({"CLAUDECODE": "1"}, {"transcript_path": str(main), "agent_id": "a1b2c3d4e5f6a7b8c"})
    assert r["agent"] == "claude-code:claude-haiku-5" and r["is_subagent"] is True


def test_remove_refused_for_claude_worker(tmp_path, ws):
    claude_tree(tmp_path, SID, worker_newer=True)
    f = ws / "research" / "sandbox" / "a.txt"
    f.write_text("x")
    ans = write_delete_answers(ws, [f])
    code, out, err = run(GATE, ["remove", "--workspace", str(ws), "--path", str(f), "--answers", str(ans)],
                         env_for(tmp_path, CLAUDECODE="1", CLAUDE_CODE_SESSION_ID=SID), tmp_path)
    assert code == 1 and "the manager removes it" in err and f.exists()


# ---------------------------------------------------------------- 5. OpenCode worker (live shape, 2026-11-11 probe)


def test_opencode_worker_has_its_own_session_row(tmp_path):
    d = tmp_path / "xdg" / "opencode"
    d.mkdir(parents=True)
    con = sqlite3.connect(d / "opencode.db")
    con.execute("create table session_v2(id text, parent_id text, agent text, model text)")
    con.execute("insert into session_v2 values ('ses_e374b2d55ffeFEaVTAkX0rfenr', NULL, NULL, "
                "'{\"id\":\"qwen3.8-flash-next\",\"providerID\":\"llamacpp\"}')")
    con.execute("insert into session_v2 values ('ses_e374af32fffeJkE1VxHay4cl6r', 'ses_e374b2d55ffeFEaVTAkX0rfenr', "
                "'general', '{\"id\":\"qwen3.8-flash-next\",\"providerID\":\"llamacpp\",\"variant\":\"default\"}')")
    con.commit()
    con.close()
    base = {"OPENCODE": "1", "XDG_DATA_HOME": str(tmp_path / "xdg"), "USERPROFILE": str(tmp_path), "HOME": str(tmp_path)}
    parent = rc.resolve_identity({**base, "OPENCODE_SESSION_ID": "ses_e374b2d55ffeFEaVTAkX0rfenr"})
    worker = rc.resolve_identity({**base, "OPENCODE_SESSION_ID": "ses_e374af32fffeJkE1VxHay4cl6r"})
    assert parent["agent"] == worker["agent"] == "opencode:llamacpp/qwen3.8-flash-next"
    assert parent["is_subagent"] is False and worker["is_subagent"] is True


# ---------------------------------------------------------------- 6. no harness catalogue in the docs


CATALOGUE = ("opencode run", "claude --resume", "codex exec", "invoke_subagent", "--fork-session",
             "auto|opencode|claude|codex|agy", '--platform "codex"')


def doc_files():
    files = [ROOT / "README.md", ROOT / "SKILL.md"]
    files += sorted((ROOT / "skills").glob("ra-*/SKILL.md"))
    files += sorted((ROOT / "references").glob("*.md"))
    return files


def test_docs_do_not_advertise_other_harnesses():
    hits = []
    for f in doc_files():
        text = f.read_text(encoding="utf-8")
        for bad in CATALOGUE:
            for ln in text.splitlines():
                # The safety notes may name CLI forms only to say they need the user's grant.
                if bad in ln and "allow-agent" not in ln and "permission" not in ln:
                    hits.append(f"{f.name}: {bad}: {ln.strip()[:80]}")
    assert not hits, hits


def test_context_fork_skill_names_native_tool_and_handover():
    text = (ROOT / "skills" / "ra-context-fork" / "SKILL.md").read_text(encoding="utf-8")
    assert "native sub-agent tool" in text and "allow-agent" in text
    assert "## Handover answers" in text
    assert text.count("RA supports OpenCode, Claude Code, Codex and Antigravity/Gemini") == 1


# ---------------------------------------------------------------- 7. answers files are used once


def write_delete_answers(w, paths, name=None):
    d = w / "research" / "answers"
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("before-delete_*.md"))) + 1
    f = d / (name or f"before-delete_{n}.md")
    shown = ", ".join(Path(p).resolve().relative_to(w.resolve()).as_posix() for p in paths)
    f.write_text(DELETE_ANSWERS.format(paths=shown), encoding="utf-8")
    return f


def remove(tmp_path, w, paths, ans, extra=()):
    args = ["remove", "--workspace", str(w), "--answers", str(ans)]
    for p in paths:
        args += ["--path", str(p)]
    return run(GATE, args + list(extra), env_for(tmp_path), tmp_path)


def test_remove_answers_file_used_once(tmp_path, ws):
    a = ws / "research" / "sandbox" / "a.txt"
    a.write_text("x")
    ans = write_delete_answers(ws, [a])
    code, out, err = remove(tmp_path, ws, [a], ans)
    assert code == 0, out + err
    a.write_text("again")
    code, out, err = remove(tmp_path, ws, [a], ans)
    assert code == 1 and "already used" in err and a.exists()
    assert "before-delete_2.md" in err  # the next free answers file, not _1
    copy = ws / "research" / "answers" / "before-delete_9.md"
    copy.write_text(ans.read_text(encoding="utf-8"), encoding="utf-8")
    code, out, err = remove(tmp_path, ws, [a], copy)
    assert code == 1 and "already used" in err and a.exists()


def test_remove_answers_must_name_each_target(tmp_path, ws):
    a = ws / "research" / "sandbox" / "a.txt"
    b = ws / "research" / "sandbox" / "b.txt"
    a.write_text("x")
    b.write_text("x")
    ans = write_delete_answers(ws, [a])
    code, out, err = remove(tmp_path, ws, [a, b], ans)
    assert code == 1 and "research/sandbox/b.txt" in err and a.exists() and b.exists()
    ans2 = write_delete_answers(ws, [a, b])
    code, out, err = remove(tmp_path, ws, [a, b], ans2)
    assert code == 0, out + err


def test_remove_answers_parent_named_by_child_only_is_refused(tmp_path, ws):
    d = ws / "research" / "sandbox" / "d"
    d.mkdir(parents=True)
    (d / "f.txt").write_text("x")
    ans = write_delete_answers(ws, [d / "f.txt"])
    code, out, err = remove(tmp_path, ws, [d], ans)
    assert code == 1 and "research/sandbox/d" in err and d.exists()


def test_allow_agent_answers_used_once_and_next_free_name(tmp_path, ws):
    adir = ws / "research" / "answers"
    adir.mkdir(exist_ok=True)
    ans = adir / "before-other-agent_1.md"
    ans.write_text(OTHER_AGENT_ANSWERS.format(n=1), encoding="utf-8")
    base = ["allow-agent", "--workspace", str(ws), "--quote", "use opencode y or codex gpt as a worker please", "--source", "chat",
            "--answers", str(ans)]
    assert run(GATE, base + ["--agent", "opencode:x/y"], env_for(tmp_path), tmp_path)[0] == 0
    code, out, err = run(GATE, base + ["--agent", "codex:gpt"], env_for(tmp_path), tmp_path)
    assert code == 1 and "already used" in err
    assert "before-other-agent_2.md" in err and "before-other-agent_1.md --" not in err
    assert not rc.is_agent_allowed(ws, "codex:gpt", own_harness="")


def test_graduate_answers_used_once(tmp_path, ws):
    def stage7(d):
        d.update({"active_hypothesis": "H001", "current_stage": "STAGE_7_GRADUATION_REVIEW",
                  "log_audit_passed": True, "visual_audit_passed": True, "cheese_audit_passed": True})
    sp = ws / "research" / ".ra_state.json"
    data = json.loads(sp.read_text(encoding="utf-8-sig"))
    stage7(data)
    sp.write_text(json.dumps(data), encoding="utf-8")
    good = ws / "research" / "answers" / "before-graduation_1.md"
    good.parent.mkdir(exist_ok=True)
    good.write_text(
        "1. It works on research/data/heldout.csv, which it never saw; the score was 0.84.\n"
        "2. Nothing was faked; I grepped for hardcoded case values and found none.\n"
        "3. The user would first notice the distance shown in millimetres, not pixels.\n"
        "4. Still a guess: behaviour on a different camera; it would degrade to the old score.\n", encoding="utf-8")
    base = ["graduate", "--workspace", str(ws), "--user-approved", "looks good, ship it", "--answers", str(good)]
    code, out, err = run(GATE, base, env_for(tmp_path), tmp_path)
    assert code == 0, out + err
    data = json.loads(sp.read_text(encoding="utf-8-sig"))
    stage7(data)
    sp.write_text(json.dumps(data), encoding="utf-8")
    code, out, err = run(GATE, base, env_for(tmp_path), tmp_path)
    assert code == 1 and "already used" in err and "before-graduation_2.md" in err


# ---------------------------------------------------------------- 8. native-path worker handover


def board(w, scores=(0.2, 0.25, 0.31)):
    sp = w / "research" / ".ra_state.json"
    d = json.loads(sp.read_text(encoding="utf-8-sig"))
    d["active_hypothesis"] = "H001"
    d["current_stage"] = "STAGE_3_SANDBOX_PROTOTYPE"
    d["stop_rules"] = {"pins": {"hypothesis": "H001", "metric": "pass_rate", "target": 0.8, "min_gain": 0.02}}
    d["scoreboard"] = {"H001": {"approaches": {"pin_distance": {
        "status": "RACING", "rounds": [{"score": s, "unseen": False} for s in scores]}}}}
    sp.write_text(json.dumps(d), encoding="utf-8")


def agent_finished(w, capfd, text, desc="pin filter"):
    payload = {"tool_name": "Agent", "tool_input": {"description": desc, "prompt": "filter the pins"},
               "tool_response": {"status": "completed", "content": [{"type": "text", "text": text}]},
               "session_id": "s1", "cwd": str(w)}
    capfd.readouterr()
    ra_hooks.on_post_tool(w, payload)
    out = capfd.readouterr().out
    return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out.strip() else ""


def review(tmp_path, w, body):
    f = w / "research" / "reviews" / "REVIEW_1.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    return run(GATE, ["review", "--workspace", str(w), "--file", "research/reviews/REVIEW_1.md"], env_for(tmp_path), tmp_path)


def test_native_finish_shows_handover_questions(ws, capfd):
    board(ws)
    text = agent_finished(ws, capfd, "I filtered the pins; result 0.31.")
    assert "# Worker handover" in text and "Did you check before submitting" in text
    assert "## Handover answers (pin filter)" in text
    assert "# Review meeting" in text


def test_review_refuses_native_worker_without_handover(tmp_path, ws, capfd):
    board(ws)
    agent_finished(ws, capfd, "I filtered the pins; result 0.31.")
    code, out, err = review(tmp_path, ws, REVIEW_BODY)
    assert code == 2 and "Handover answers (pin filter)" in err and "Worker handover" in err
    code, out, err = review(tmp_path, ws, REVIEW_BODY + "\n## Handover answers (pin filter)\n1. yes\n")
    assert code == 2 and "question 1" in err
    code, out, err = review(tmp_path, ws, REVIEW_BODY + "\n## Handover answers (pin filter)\n" + HANDOVER)
    assert code == 0, out + err


def test_review_accepts_handover_in_agent_result(tmp_path, ws, capfd):
    board(ws)
    text = agent_finished(ws, capfd, "Report.\n\n## Handover answers\n" + HANDOVER)
    assert "# Worker handover" not in text
    code, out, err = review(tmp_path, ws, REVIEW_BODY)
    assert code == 0, out + err


def test_review_accepts_handover_in_report_file(tmp_path, ws, capfd):
    board(ws)
    agent_finished(ws, capfd, "Done, see my report file.", desc="Subagent_A")
    rp = ws / "research" / "context_snapshots" / "reports" / "REPORT_Subagent_A.md"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("# Report\n\n## Handover answers\n" + HANDOVER, encoding="utf-8")
    code, out, err = review(tmp_path, ws, REVIEW_BODY)
    assert code == 0, out + err


def test_review_after_return_baton_needs_no_handover_section(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    w = tmp_path / "ws"
    w.mkdir()
    assert run(GATE, ["init", "--workspace", str(w)], env, tmp_path)[0] == 0
    board(w)
    assert run(HARNESS, ["create", "--workspace", str(w), "--id", "base", "--tier", "workflow_slice", "--summary", "ctx"],
               env, tmp_path)[0] == 0
    assert run(HARNESS, ["fork", "--workspace", str(w), "--subagent", "Subagent_A", "--snapshots", "base",
                         "--task", "filter the pins"], env, tmp_path)[0] == 0
    rp = w / "research" / "context_snapshots" / "reports" / "REPORT_Subagent_A.md"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("# Report\nok\n\n## Handover answers\n" + HANDOVER, encoding="utf-8")
    assert run(HARNESS, ["return-baton", "--workspace", str(w), "--subagent", "Subagent_A", "--status", "COMPLETED"],
               env, tmp_path)[0] == 0
    rp.unlink()  # accepted at return-baton; the review does not ask again
    f = w / "research" / "reviews" / "REVIEW_1.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(REVIEW_BODY, encoding="utf-8")
    code, out, err = run(GATE, ["review", "--workspace", str(w), "--file", "research/reviews/REVIEW_1.md"], env, tmp_path)
    assert code == 0, out + err


# ---------------------------------------------------------------- 9. mv / Move-Item evasion


MOVE_BLOCKS = [
    ("Bash", "mv research/DECISIONS.md ../D.md"),
    ("PowerShell", r"Move-Item research\LAB_LOG.md C:\tmp"),
    ("PowerShell", "Move-Item -Path research/LAB_LOG.md -Destination research/old.md"),
    ("PowerShell", "Move-Item -Destination research/old.md -Path research/DIRECTIVES.md"),
    ("Bash", "mv research/sandbox/a ../out"),
    ("Bash", "mv -t ../out research/sandbox/a"),
    ("Bash", "mv research/sandbox/a ~/a.bak"),
    ("PowerShell", r"ren research\DECISIONS.md D.md"),
    ("PowerShell", r"move research\sandbox\a C:\elsewhere"),
    ("Bash", "mv research/*.md ../"),
    ("Bash", "mv research/hypotheses/H1 research/old_H1"),
    ("Bash", "mv -f research/sandbox/a /tmp/a"),
]

MOVE_PASSES = [
    ("Bash", "mv research/sandbox/a research/sandbox/b"),
    ("PowerShell", "Move-Item research/sandbox/a research/sandbox/b"),
    ("Bash", "mv -f research/sandbox/a research/notes/a.md"),
    ("PowerShell", r"ren research\sandbox\a b"),
]


def _move_ws(ws):
    (ws / "research" / "sandbox" / "a").write_text("x")
    (ws / "research" / "DECISIONS.md").write_text("d")
    (ws / "research" / "DIRECTIVES.md").write_text("d")
    (ws / "research" / "hypotheses" / "H1").mkdir(parents=True, exist_ok=True)
    (ws / "research" / "hypotheses" / "H1" / "REPORT.md").write_text("r")


@pytest.mark.parametrize("tool,cmd", MOVE_BLOCKS)
def test_hook_blocks_move_as_delete(tmp_path, ws, tool, cmd):
    _move_ws(ws)
    code, err = hook(tmp_path, ws, tool, cmd)
    assert code == 2 and "Before delete" in err and "mv x ../x.bak" in err, (cmd, err)


@pytest.mark.parametrize("tool,cmd", MOVE_PASSES)
def test_hook_passes_move_inside_workspace(tmp_path, ws, tool, cmd):
    _move_ws(ws)
    code, err = hook(tmp_path, ws, tool, cmd)
    assert code == 0, (cmd, err)


def test_move_worked_example_in_templates():
    for moment in ("session-start", "before-delete"):
        assert "mv x ../x.bak" in rc.load_injection(moment)["body"], moment


# ---------------------------------------------------------------- 1/2/9/10/15. OpenCode rules


def oc_regex(pattern):
    return "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in pattern)


def oc_matches(pattern, command):
    """OpenCode-style: `*` crosses `/`, backslashes normalised, case folded (Windows), `x *` also matches `x`."""
    cmd = command.replace("\\", "/")
    pats = [pattern] + ([pattern[:-2]] if pattern.endswith(" *") else [])
    return any(re.fullmatch(oc_regex(p), cmd, re.IGNORECASE | re.DOTALL) for p in pats)


def oc_effect(rules, command):
    eff = None
    for r in rules:
        if r["action"] == "shell" and oc_matches(r["resource"], command):
            eff = r["effect"]
    return eff


EVERYDAY = REVIEW_FOCUS_PASS + [
    "git checkout main", "git checkout -b feat/x", "git rm --cached x", "git rm -r --cached dir", "git log --oneline -5",
    "ls src", "python -m pytest tests -q", "npm test", "npm run build", "timeout 60 python -m pytest tests -q",
    "env FOO=1 npm test", "nice -n 10 make", "bash scripts/build.sh", 'bash -c "npm run build --platform win32"',
    'bash -c "echo confirm transform"', 'pwsh -NoProfile -Command "Get-ChildItem src"', 'cmd /c "dir /b src"',
    "mv research/sandbox/a research/sandbox/b", "Move-Item research/sandbox/a research/sandbox/b", "node scripts/build.js",
    'python -c "print(1)"', "type claude_notes.md", "cat src/claude_shim.py", "cd ~/projects/claude-web",
    "ls ~/.claude/skills", "Get-Content claude_notes.md", "python -I scripts/ra_gate.py status --workspace .",
    'pwsh -c "Write-Output hi"', "npx prettier --write src", "find . -name '*.py'", "echo hi | xargs echo",
]

OC_DENIED = [
    "rm -rf x", "timeout 60 rm -rf x", "nice rm -rf x", "env -i rm x", "env FOO=1 rm x", "nohup rm x", "sudo rm -r x",
    r"C:\x\claude.exe -p hi", "C:/Users/x/AppData/Roaming/npm/claude.cmd -p hi", "/usr/local/bin/codex exec y",
    "npx claude -p hi", "bunx opencode run x", 'bash -c "rm -rf x"', "bash -lc 'rm x'", 'cmd /c "del x"',
    "cmd /c rd /s /q x", 'pwsh -c "Remove-Item x"', 'powershell -NoProfile -Command "Remove-Item -Recurse x"',
    'bash -c "claude -p x"', 'pwsh -c "codex exec y"', "find . -name x -delete", "find . -exec rm {} ;", "xargs rm",
    "xargs -0 rm -f", 'python -c "import shutil;shutil.rmtree(\'x\')"', "python3 -Ic \"import os;os.remove('x')\"",
    "node -e \"require('fs').rmSync('x')\"", "git checkout -- a.py", "git checkout .", "git checkout HEAD -- a.py",
    "git restore a.py", "git rm a.py", "git clean -fd", "git reset --hard", "mv research/DECISIONS.md ../D.md",
    "Move-Item research/LAB_LOG.md C:/tmp", "move research/DIRECTIVES.md x", "where claude", "which opencode",
    "Get-Command codex",
]


def test_opencode_rules_never_match_review_focus_pass_list():
    rules = ra_forge.build_opencode_rules(["opencode", "claude-code", "codex", "agy"]) + ra_forge.build_opencode_rules([])
    bad = [(cmd, r["resource"]) for cmd in REVIEW_FOCUS_PASS for r in rules
           if r["action"] == "shell" and r["effect"] == "deny" and oc_matches(r["resource"], cmd)]
    assert not bad, bad


@pytest.mark.parametrize("granted", [[], ["opencode", "claude-code", "codex", "agy"]])
def test_opencode_rules_never_deny_everyday_commands(granted):
    rules = ra_forge.build_opencode_rules(granted)
    bad = [cmd for cmd in EVERYDAY if oc_effect(rules, cmd) == "deny"]
    assert not bad, bad


@pytest.mark.parametrize("cmd", OC_DENIED)
def test_opencode_rules_deny(cmd):
    assert oc_effect(ra_forge.build_opencode_rules([]), cmd) == "deny", cmd


@pytest.mark.parametrize("cmd,effect", [
    ("mv research/sandbox/x ../x.bak", None), ('bash -c "x;rm y"', None), ("type claude", None),
    ("ls ~/AppData/Roaming/npm", None), ("git checkout src/a.py", None), ("perl -e 'unlink q(x)'", None),
    ("git restore --staged x", "deny"), ("ls src/claude", "deny"), ('bash -c "echo rm me"', "deny"),
])
def test_readme_opencode_gaps_are_accurate(cmd, effect):
    assert oc_effect(ra_forge.build_opencode_rules([]), cmd) == effect, cmd
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "What the OpenCode rules do not cover" in readme


def test_opencode_named_patterns_present():
    res = {r["resource"] for r in ra_forge.build_opencode_rules([]) if r["effect"] == "deny"}
    for p in ("timeout * rm *", "nice * rm *", "env * rm *", "git checkout .*", "git checkout -- *", "git restore *",
              "git rm *", "*/claude *", "*/claude.exe*", "npx claude*", "bunx claude*", "find * -delete*", "xargs rm*",
              "mv *DECISIONS.md*", "Move-Item *DECISIONS.md*"):
        assert p in res, p
    assert not any(r.startswith(("type ", "Type ")) for r in res)


def test_opencode_git_rm_cached_allowed_after_deny():
    rules = ra_forge.build_opencode_rules([])
    assert oc_effect(rules, "git rm --cached x") == "allow"
    assert oc_effect(rules, "git rm -r --cached dir") == "allow"
    assert oc_effect(rules, "git rm x") == "deny"


def test_opencode_grant_allows_full_path_forms_but_not_deletes():
    rules = ra_forge.build_opencode_rules(["claude-code"])
    assert oc_effect(rules, "claude -p hi") == "allow"
    assert oc_effect(rules, r"C:\x\claude.exe -p hi") == "allow"
    assert oc_effect(rules, "npx claude -p hi") == "allow"
    assert oc_effect(rules, "codex exec y") == "deny"
    assert oc_effect(rules, 'bash -c "claude -p x; rm -rf y"') == "deny"
    assert oc_effect(rules, "where claude") == "deny"


# ---------------------------------------------------------------- 11. derived question count


def test_dispatch_block_counts_review_questions(tmp_path, ws, capfd):
    board(ws)
    agent_finished(ws, capfd, "done")
    n = len(rc.load_injection("review-meeting")["questions"])
    capfd.readouterr()
    code = ra_hooks.on_pre_tool(ws, {"tool_name": "Agent", "tool_input": {"description": "next"}, "session_id": "s1",
                                     "cwd": str(ws)})
    err = capfd.readouterr().err
    assert code == 2 and f"the {n} review-meeting questions" in err and "five" not in err


# ---------------------------------------------------------------- 12. hook identity from the transcript


def test_hook_identity_from_transcript(tmp_path, ws):
    main, worker = claude_tree(tmp_path, SID, main_model="claude-sonnet-5-5", worker_model="claude-haiku-5",
                               worker_newer=False)
    code, err = hook(tmp_path, ws, "Bash", "claude -p hi", transcript_path=str(main))
    assert code == 2 and "claude-code:claude-sonnet-5-5" in err and "claude-code:unknown" not in err
    code, err = hook(tmp_path, ws, "Bash", "claude -p hi", transcript_path=str(main), agent_id="a1b2c3d4e5f6a7b8c")
    assert code == 2 and "claude-code:claude-haiku-5" in err


def test_session_start_identity_from_transcript(tmp_path, ws):
    main, _ = claude_tree(tmp_path, SID, main_model="claude-sonnet-5-5", worker_newer=False)
    payload = {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(ws), "session_id": SID,
               "transcript_path": str(main)}
    code, out, err = run(HOOKS, ["session-start"], env_for(tmp_path), ws, json.dumps(payload).encode())
    assert code == 0, err
    assert "You are: claude-code:claude-sonnet-5-5" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


# ---------------------------------------------------------------- 14. commented OpenCode config


def test_forge_with_commented_opencode_config_still_forges_claude_hooks(tmp_path, ws):
    oc = ws / ".opencode" / "opencode.jsonc"
    oc.parent.mkdir()
    oc.write_text('{\n  // my note\n  "permissions": []\n}\n', encoding="utf-8")
    code, out, err = run(FORGE, ["--workspace", str(ws), "--name", "demo", "--domain", "test"], env_for(tmp_path), tmp_path)
    assert code == 0, out + err
    assert "ra_hooks.py" in (ws / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    assert "WARNING" in err and "OpenCode" in err
    assert oc.read_text(encoding="utf-8") == '{\n  // my note\n  "permissions": []\n}\n'


# ---------------------------------------------------------------- 15. `type` is Get-Content in PowerShell


@pytest.mark.parametrize("cmd", ["type claude_notes.md", r"type src\claude\notes.txt", "type ~/bin/claude"])
def test_type_with_a_file_passes(cmd):
    assert ra_hooks.shell_safety(cmd) == [], cmd


@pytest.mark.parametrize("cmd", ["type claude", "type codex", "type claude.exe"])
def test_type_of_an_agent_name_is_a_lookup(cmd):
    assert kinds(cmd) == {"agent-lookup"}, cmd


# ---------------------------------------------------------------- 20. no reusable session id for native dispatch


def test_fork_prints_no_session_id_for_native_dispatch(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    w = tmp_path / "ws"
    w.mkdir()
    assert run(GATE, ["init", "--workspace", str(w)], env, tmp_path)[0] == 0
    assert run(HARNESS, ["create", "--workspace", str(w), "--id", "base", "--tier", "workflow_slice", "--summary", "ctx",
                         "--base-session", "ses_main"], env, tmp_path)[0] == 0
    code, out, err = run(HARNESS, ["fork", "--workspace", str(w), "--subagent", "Subagent_A", "--snapshots", "base",
                                   "--task", "filter the pins"], env, tmp_path)
    assert code == 0, out + err
    assert "ses_main" not in out and "Native Session Fork" not in out
    assert 'agent="general"' in out
