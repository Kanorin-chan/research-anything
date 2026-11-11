import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ra_common as rc  # noqa: E402

GATE = ROOT / "scripts" / "ra_gate.py"
HARNESS_VARS = ("OPENCODE", "OPENCODE_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                "CODEX_HOME", "CODEX_SANDBOX", "ANTIGRAVITY_CLI", "GEMINI_CLI", "XDG_DATA_HOME")
QWEN = '{"id":"qwen3.8-flash-next","providerID":"llamacpp","variant":"high"}'


def make_db(tmp_path, rows, table="session_v2"):
    d = tmp_path / "xdg" / "opencode"
    d.mkdir(parents=True)
    con = sqlite3.connect(d / "opencode.db")
    con.execute(f"create table {table}(id text, parent_id text, model text)")
    con.executemany(f"insert into {table} values (?,?,?)", rows)
    con.commit()
    con.close()
    return tmp_path / "xdg"


def oc_env(xdg, sid="ses_1"):
    return {"OPENCODE": "1", "OPENCODE_SESSION_ID": sid, "XDG_DATA_HOME": str(xdg), "USERPROFILE": str(xdg), "HOME": str(xdg)}


def test_opencode_identity_from_db(tmp_path):
    xdg = make_db(tmp_path, [("ses_1", None, QWEN)])
    r = rc.resolve_identity(oc_env(xdg))
    assert r["agent"] == "opencode:llamacpp/qwen3.8-flash-next"
    assert r["harness"] == "opencode" and r["session"] == "ses_1" and r["is_subagent"] is False


def test_opencode_subagent_and_old_table(tmp_path):
    xdg = make_db(tmp_path, [("ses_1", "ses_0", QWEN)], table="session")
    r = rc.resolve_identity(oc_env(xdg))
    assert r["agent"] == "opencode:llamacpp/qwen3.8-flash-next" and r["is_subagent"] is True


def test_opencode_identity_db_missing(tmp_path):
    r = rc.resolve_identity(oc_env(tmp_path / "nothing"))
    assert r["agent"] == "opencode:unknown"


def test_opencode_identity_db_locked(tmp_path):
    xdg = make_db(tmp_path, [("ses_1", None, QWEN)])
    db = xdg / "opencode" / "opencode.db"
    con = sqlite3.connect(db, isolation_level=None)
    con.execute("pragma journal_mode=delete")
    con.execute("begin exclusive")
    try:
        t = time.time()
        r = rc.resolve_identity(oc_env(xdg))
        assert time.time() - t < 5
        assert r["agent"] in ("opencode:unknown", "opencode:llamacpp/qwen3.8-flash-next")
        assert "claude" not in r["agent"]
    finally:
        con.execute("rollback")
        con.close()


def test_opencode_identity_garbage_db(tmp_path):
    d = tmp_path / "xdg" / "opencode"
    d.mkdir(parents=True)
    (d / "opencode.db").write_bytes(b"not a database at all" * 50)
    assert rc.resolve_identity(oc_env(tmp_path / "xdg"))["agent"] == "opencode:unknown"


def test_opencode_identity_no_row(tmp_path):
    xdg = make_db(tmp_path, [("ses_other", None, QWEN)])
    assert rc.resolve_identity(oc_env(xdg))["agent"] == "opencode:unknown"


def test_claude_identity_from_payload_model():
    env = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "abc"}
    r = rc.resolve_identity(env, {"model": "claude-opus-5-5", "agent_id": "sub1"})
    assert r["agent"] == "claude-code:claude-opus-5-5" and r["is_subagent"] is True and r["source"] == "payload"
    assert rc.resolve_identity(env, {"model": "claude-opus-5-5"})["is_subagent"] is False


def _line(obj):
    return json.dumps(obj) + "\n"


def test_claude_identity_from_transcript_tail(tmp_path):
    sid = "11111111-2222-3333-4444-555555555555"
    proj = tmp_path / ".claude" / "projects" / "C--x"
    proj.mkdir(parents=True)
    tr = proj / f"{sid}.jsonl"
    with open(tr, "w", encoding="utf-8") as f:
        f.write(_line({"type": "assistant", "message": {"model": "old-model"}}))
        filler = _line({"type": "user", "message": {"content": "x" * 1000}})
        for _ in range(50 * 1024):
            f.write(filler)
        f.write(_line({"type": "assistant", "message": {"model": "claude-sonnet-5-5"}}))
        f.write(_line({"type": "user", "message": {"content": "hi"}}))
    assert tr.stat().st_size > 50 * 1024 * 1024
    env = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": sid, "USERPROFILE": str(tmp_path), "HOME": str(tmp_path)}
    t = time.time()
    r = rc.resolve_identity(env, {})
    assert time.time() - t < 1
    assert r["agent"] == "claude-code:claude-sonnet-5-5" and r["source"] == "transcript"
    # also via an explicit transcript_path
    assert rc.resolve_identity({"CLAUDECODE": "1"}, {"transcript_path": str(tr)})["model"] == "claude-sonnet-5-5"


def test_claude_identity_transcript_without_assistant(tmp_path):
    tr = tmp_path / "t.jsonl"
    tr.write_text(_line({"type": "user", "message": {"content": "hi"}}), encoding="utf-8")
    assert rc.resolve_identity({"CLAUDECODE": "1"}, {"transcript_path": str(tr)})["agent"] == "claude-code:unknown"
    assert rc.resolve_identity({"CLAUDECODE": "1"}, {"transcript_path": str(tmp_path / "gone")})["agent"] == "claude-code:unknown"


def test_other_harnesses_and_none():
    assert rc.resolve_identity({"CODEX_HOME": "x"})["agent"] == "codex:unknown"
    assert rc.resolve_identity({"GEMINI_CLI": "1"})["agent"] == "agy:unknown"
    assert rc.resolve_identity({})["agent"] == "unknown"


def test_nested_ancestor_wins_and_fallback(monkeypatch):
    env = {"OPENCODE": "1", "CLAUDECODE": "1"}
    monkeypatch.setattr(rc, "_ancestor_harness", lambda c: "claude-code")
    r = rc.resolve_identity(env, {"model": "m"})
    assert r["harness"] == "claude-code" and r["source"] == "payload"
    monkeypatch.setattr(rc, "_ancestor_harness", lambda c: None)
    r = rc.resolve_identity(env, {"model": "m"})
    assert r["harness"] == "opencode" and r["source"] == "nested-guess"


def gate(ws, env, *args):
    return subprocess.run([sys.executable, "-I", str(GATE), *args, "--workspace", str(ws)],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ws))


def clean_env(extra):
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    env.update(extra)
    return env


def test_claimed_name_never_used(tmp_path):
    xdg = make_db(tmp_path, [("ses_1", None, QWEN)])
    env = clean_env(oc_env(xdg))
    ws = tmp_path / "ws"
    ws.mkdir()
    assert gate(ws, env, "init", "--agent", "claude-opus-5-5").returncode == 0
    p = gate(ws, env, "decide", "--what", "use the small cache", "--why", "measured faster on real data",
             "--agent", "claude-opus-5-5")
    assert p.returncode == 0, p.stderr
    assert "You wrote --agent claude-opus-5-5, but you are opencode:llamacpp/qwen3.8-flash-next" in p.stderr
    state = json.loads((ws / "research" / ".ra_state.json").read_text(encoding="utf-8"))
    assert state["history"][0]["agent"] == "opencode:llamacpp/qwen3.8-flash-next"
    assert state["history"][0]["agent_claimed"] == "claude-opus-5-5"
    dec = (ws / "research" / "DECISIONS.md").read_text(encoding="utf-8")
    assert "opencode:llamacpp/qwen3.8-flash-next" in dec and "claude-opus-5-5" not in dec


def test_old_state_file_still_works(tmp_path):
    xdg = make_db(tmp_path, [("ses_1", None, QWEN)])
    env = clean_env(oc_env(xdg))
    ws = tmp_path / "ws"
    ws.mkdir()
    assert gate(ws, env, "init").returncode == 0
    sp = ws / "research" / ".ra_state.json"
    state = json.loads(sp.read_text(encoding="utf-8"))
    state["history"] = [
        {"timestamp": "2026-01-01T00:00:00Z", "agent": "PRIMARY_AGENT", "event": "INIT"},
        {"timestamp": "2026-01-02T00:00:00Z", "agent": "claude-opus-5-5", "event": "MAP_CONTEXT"},
    ]
    sp.write_text(json.dumps(state), encoding="utf-8")
    (ws / "a.py").write_text("x = 1\n", encoding="utf-8")
    p = gate(ws, env, "map-context", "--files", "a.py")
    assert p.returncode == 0, p.stderr
    p = gate(ws, env, "decide", "--what", "keep the old format", "--why", "old records must stay readable")
    assert p.returncode == 0, p.stderr
    assert "You wrote" not in p.stderr
    hist = json.loads(sp.read_text(encoding="utf-8"))["history"]
    assert hist[0]["agent"] == "PRIMARY_AGENT" and hist[1]["agent"] == "claude-opus-5-5"
    assert hist[-1]["agent"] == "opencode:llamacpp/qwen3.8-flash-next"
    assert "agent_claimed" not in hist[-1]


def test_agent_flag_still_parses_everywhere():
    p = subprocess.run([sys.executable, "-I", str(GATE), "--help"], capture_output=True, text=True)
    assert p.returncode == 0
