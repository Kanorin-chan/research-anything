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
QUOTE = "to use opencode qwen 3.8 flash as one of your subagent"



def other_agent_answers(tmp_path):
    """A fresh answers file per call: each one approves one grant."""
    n = len(list(tmp_path.glob("before-other-agent_*.md"))) + 1
    f = tmp_path / f"before-other-agent_{n}.md"
    f.write_text(
        f"1. The user said in chat today: use that agent as one of your workers (grant {n}).\n"
        "2. The task needs a second model for the cold review; I cannot do that myself.\n"
        "3. It may read research/ and write only research/sandbox/H001/.\n",
        encoding="utf-8")
    return f

def env_for(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    home = str(tmp_path / "home")
    env.update({"USERPROFILE": home, "HOME": home, "PYTHONUTF8": "1"})
    env.update(extra)
    return env


def oc_env(tmp_path, sid="ses_main"):
    return env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID=sid)


def run(script, args, env, cwd):
    p = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, env=env, cwd=str(cwd))
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def make_ws(tmp_path, env):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert run(GATE, ["init", "--workspace", str(ws)], env, tmp_path)[0] == 0
    code, out, err = run(HARNESS, ["create", "--workspace", str(ws), "--id", "base", "--tier", "workflow_slice",
                                   "--summary", "shared context"], env, tmp_path)
    assert code == 0, out + err
    return ws


def fork(ws, env, tmp_path, name="Subagent_A", extra=()):
    return run(HARNESS, ["fork", "--workspace", str(ws), "--subagent", name, "--snapshots", "base",
                         "--task", "check the thing", *extra], env, tmp_path)


def test_allow_agent_requires_quote(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    base = ["allow-agent", "--workspace", str(ws), "--agent", "opencode:llamacpp/qwen3.8-flash-next", "--source", "chat",
            "--answers", str(other_agent_answers(tmp_path))]
    assert run(GATE, base, env, tmp_path)[0] == 1
    assert run(GATE, base + ["--quote", "yes"], env, tmp_path)[0] == 1
    assert not (ws / "research" / "AGENT_PERMISSIONS.json").exists()
    assert run(GATE, base + ["--quote", QUOTE], env, tmp_path)[0] == 0


def test_grant_and_revoke_roundtrip(tmp_path):
    env = env_for(tmp_path, CLAUDECODE="1")
    ws = make_ws(tmp_path, env)
    agent = "opencode:llamacpp/qwen3.8-flash-next"
    assert not rc.is_agent_allowed(ws, agent)
    rc.grant_agent(ws, agent, QUOTE, "chat 2026-11-11")
    data = json.loads((ws / "research" / "AGENT_PERMISSIONS.json").read_text(encoding="utf-8"))
    assert data["allow"][0]["quote"] == QUOTE and data["allow"][0]["use"] is True
    assert rc.is_agent_allowed(ws, agent)
    assert not rc.is_agent_allowed(ws, "opencode")  # a bare launch runs the default model: needs a harness-wide grant
    assert not rc.is_agent_allowed(ws, "codex")
    assert rc.revoke_agent(ws, agent) is True
    assert not rc.is_agent_allowed(ws, agent)
    assert rc.revoke_agent(ws, agent) is False
    # CLI path too
    assert run(GATE, ["allow-agent", "--workspace", str(ws), "--agent", agent, "--quote", QUOTE, "--source", "chat",
                     "--answers", str(other_agent_answers(tmp_path))],
               env, tmp_path)[0] == 0
    assert rc.is_agent_allowed(ws, agent)
    assert run(GATE, ["revoke-agent", "--workspace", str(ws), "--agent", agent], env, tmp_path)[0] == 0
    assert not rc.is_agent_allowed(ws, agent)


def test_own_harness_always_allowed(tmp_path, monkeypatch):
    for k in HARNESS_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    ws = tmp_path / "ws"
    assert rc.is_agent_allowed(ws, "claude-code")
    assert rc.is_agent_allowed(ws, "claude")
    assert not rc.is_agent_allowed(ws, "codex")


def test_fork_prints_only_own_harness(tmp_path):
    env = oc_env(tmp_path)
    ws = make_ws(tmp_path, env)
    code, out, err = fork(ws, env, tmp_path)
    assert code == 0, out + err
    assert 'agent="general"' in out  # own harness: native tool, no CLI without a grant
    for banned in ("opencode run", "claude --resume", "codex exec", "invoke_subagent", "Agent(subagent_type", "Agent tool"):
        assert banned not in out
    assert "One fresh worker per task" in out  # worker-dispatch injection


def test_fork_own_harness_cli_only_with_grant(tmp_path):
    env = oc_env(tmp_path)
    ws = make_ws(tmp_path, env)
    rc.grant_agent(ws, "opencode:llamacpp/qwen3.8-flash-next", QUOTE, "chat")
    code, out, err = fork(ws, env, tmp_path)
    assert code == 0, out + err
    assert "opencode run" in out


def test_fork_brief_carries_handover_questions(tmp_path):
    env = oc_env(tmp_path)
    ws = make_ws(tmp_path, env)
    assert fork(ws, env, tmp_path)[0] == 0
    brief = (ws / "research" / "context_snapshots" / "forks" / "FORK_Subagent_A.md").read_text(encoding="utf-8")
    assert "## Handover answers" in brief and "Did you check before submitting" in brief
    assert "check the thing" in brief and "{unknown" not in brief


def test_fork_other_platform_refused_without_grant(tmp_path):
    env = oc_env(tmp_path)
    ws = make_ws(tmp_path, env)
    code, out, err = fork(ws, env, tmp_path, extra=["--platform", "codex"])
    assert code == 1
    assert "Before using another agent" in out + err and "codex" in out + err
    assert "codex exec" not in out
    assert json.loads((ws / "research" / "context_snapshots" / "SNAPSHOT_REGISTRY.json").read_text(encoding="utf-8"))[
        "outstanding_forks"] == {}


def test_fork_other_platform_allowed_with_grant(tmp_path):
    env = oc_env(tmp_path)
    ws = make_ws(tmp_path, env)
    rc.grant_agent(ws, "codex:gpt-5", "use codex for the review work please", "chat")
    code, out, err = fork(ws, env, tmp_path, extra=["--platform", "codex"])
    assert code == 0, out + err
    assert "codex exec" in out and 'agent="general"' in out
    assert "claude --resume" not in out and "invoke_subagent" not in out


def test_fork_current_platform_name_still_works(tmp_path):
    env = env_for(tmp_path, CLAUDECODE="1", CLAUDE_CODE_SESSION_ID="nosuch")
    ws = make_ws(tmp_path, env)
    code, out, err = fork(ws, env, tmp_path, extra=["--platform", "claude"])
    assert code == 0, out + err
    assert "Agent tool (subagent_type" in out and "claude --resume" not in out and "opencode run" not in out


def test_detect_platform_no_path_discovery(tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    for n in ("claude", "claude.cmd", "claude.exe", "opencode.cmd", "codex.cmd"):
        (fake / n).write_text("@echo off\n", encoding="utf-8")
    env = env_for(tmp_path)
    env["PATH"] = str(fake) + os.pathsep + env.get("PATH", "")
    code = ("import sys; sys.path.insert(0, r'%s'); import ra_context_harness as h; print(h.detect_platform('auto'))"
            % (ROOT / "scripts"))
    p = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, env=env, cwd=str(tmp_path))
    out = p.stdout.decode().strip()
    assert p.returncode == 0 and out not in ("claude", "opencode", "codex", "agy"), out


def test_fork_unknown_harness_native_only(tmp_path):
    env = env_for(tmp_path)
    ws = make_ws(tmp_path, env)
    code, out, err = fork(ws, env, tmp_path)
    assert code == 0, out + err
    for banned in ("opencode run", "claude --resume", "codex exec", "invoke_subagent", "Agent(subagent_type"):
        assert banned not in out


def test_fork_refuses_session_of_other_worker(tmp_path):
    env = oc_env(tmp_path, "ses_main")
    ws = make_ws(tmp_path, env)
    # Worker A runs in session ses_A (not the manager's own session).
    code, out, err = fork(ws, env, tmp_path, "Subagent_TESTSET", ["--base-session", "ses_A"])
    assert code == 0, out + err
    # A different worker name must not be sent into that session.
    code, out, err = fork(ws, env, tmp_path, "Subagent_NEWTASK", ["--base-session", "ses_A", "--parallel"])
    assert code == 1
    assert "Subagent_TESTSET" in out + err
    # The manager's own session is fine to fork from, by any worker.
    code, out, err = fork(ws, env, tmp_path, "Subagent_NEWTASK", ["--base-session", "ses_main", "--parallel"])
    assert code == 0, out + err
