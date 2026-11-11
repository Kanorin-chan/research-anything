import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ra_common as rc  # noqa: E402
import ra_forge  # noqa: E402

GATE = ROOT / "scripts" / "ra_gate.py"
FORGE = ROOT / "scripts" / "ra_forge.py"
QUOTE = "to use opencode qwen 3.8 flash as one of your subagent"
AGENT = "opencode:llamacpp/qwen3.8-flash-next"



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

def env_for(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("OPENCODE", "OPENCODE_SESSION_ID", "CLAUDECODE")}
    home = str(tmp_path / "home")
    env.update({"USERPROFILE": home, "HOME": home, "PYTHONUTF8": "1"})
    return env


def run(script, args, tmp_path):
    p = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True, env=env_for(tmp_path), cwd=str(tmp_path))
    return p.returncode, p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")


def cfg(ws):
    return json.loads((ws / ".opencode" / "opencode.jsonc").read_text(encoding="utf-8"))


def agent_allows(rules):
    """Allow rules other than the fixed ones (`git rm --cached`, everyday searches): only a grant adds those."""
    fixed = {f"{h} *" for h in ra_forge.OPENCODE_EVERYDAY_HEADS}
    return [r for r in rules if r["effect"] == "allow" and not r["resource"].startswith("git rm ") and r["resource"] not in fixed]


def denied(rules, resource):
    return {"action": "shell", "resource": resource, "effect": "deny"} in rules


def allowed(rules, resource):
    return {"action": "shell", "resource": resource, "effect": "allow"} in rules


def test_merge_writes_deny_rules(tmp_path):
    p = ra_forge.merge_opencode_permissions(tmp_path, [])
    rules = cfg(tmp_path)["permissions"]
    assert p == tmp_path / ".opencode" / "opencode.jsonc"
    for r in ("rm *", "Remove-Item *", "del *", "git clean *", "git reset --hard*", "claude *", "opencode *", "agy *",
              "where claude*", "Get-Command codex*", "which opencode*"):
        assert denied(rules, r), r
    assert not agent_allows(rules)
    assert {r["action"] for r in rules} == {"shell", "opencode_models"}
    assert (tmp_path / ".opencode" / ".ra_rules.json").exists()


def test_merge_keeps_user_entries(tmp_path):
    (tmp_path / ".opencode").mkdir()
    mine = [{"action": "read", "resource": "*.secret", "effect": "deny"}, {"action": "shell", "resource": "make *", "effect": "allow"}]
    (tmp_path / ".opencode" / "opencode.jsonc").write_text(json.dumps({"model": "x/y", "permissions": mine}), encoding="utf-8")
    ra_forge.merge_opencode_permissions(tmp_path, [])
    data = cfg(tmp_path)
    assert data["model"] == "x/y"
    assert data["permissions"][:2] == mine  # user's first, RA's at the end so last match wins
    assert denied(data["permissions"][2:], "rm *")
    assert (tmp_path / ".opencode" / "opencode.jsonc.bak").exists()


def test_merge_idempotent(tmp_path):
    ra_forge.merge_opencode_permissions(tmp_path, [])
    first = cfg(tmp_path)
    ra_forge.merge_opencode_permissions(tmp_path, [])
    assert cfg(tmp_path) == first


def test_granted_agent_unblocked(tmp_path):
    ra_forge.merge_opencode_permissions(tmp_path, ["opencode"])
    rules = cfg(tmp_path)["permissions"]
    assert allowed(rules, "opencode *")
    assert rules.index({"action": "shell", "resource": "opencode *", "effect": "allow"}) > \
        rules.index({"action": "shell", "resource": "opencode *", "effect": "deny"})
    assert denied(rules, "claude *")
    # revoking drops the allow again, without duplicating anything
    ra_forge.merge_opencode_permissions(tmp_path, [])
    assert not agent_allows(cfg(tmp_path)["permissions"])


def test_agy_grant_covers_all_its_clis(tmp_path):
    ra_forge.merge_opencode_permissions(tmp_path, ["agy"])
    rules = cfg(tmp_path)["permissions"]
    for r in ("agy *", "antigravity *", "gemini *"):
        assert allowed(rules, r)


def test_no_python_allow_rule(tmp_path):
    ra_forge.merge_opencode_permissions(tmp_path, ["opencode", "claude-code"])
    assert not any("python" in r["resource"] for r in cfg(tmp_path)["permissions"])


@pytest.mark.parametrize("text", ['{\n // comment\n "permissions": []\n}', "{not json", "[]", '{"permissions": {}}'])
def test_unusable_existing_config_aborts(tmp_path, text):
    (tmp_path / ".opencode").mkdir()
    f = tmp_path / ".opencode" / "opencode.jsonc"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(SystemExit):
        ra_forge.merge_opencode_permissions(tmp_path, [])
    assert f.read_text(encoding="utf-8") == text


def test_gate_grant_and_revoke_rerun_merge(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert run(GATE, ["init", "--workspace", str(ws)], tmp_path)[0] == 0
    # no RA-written config yet: granting must not create one
    code, out = run(GATE, ["allow-agent", "--workspace", str(ws), "--agent", AGENT, "--quote", QUOTE, "--source", "chat", "--answers", str(other_agent_answers(tmp_path))], tmp_path)
    assert code == 0, out
    assert not (ws / ".opencode").exists()
    ra_forge.merge_opencode_permissions(ws, rc.granted_agents(ws))
    # A model grant allows that model's -m forms only, never the bare `opencode *`.
    assert allowed(cfg(ws)["permissions"], "opencode * -m llamacpp/qwen3.8-flash-next *")
    assert not allowed(cfg(ws)["permissions"], "opencode *")
    assert run(GATE, ["revoke-agent", "--workspace", str(ws), "--agent", AGENT], tmp_path)[0] == 0
    assert not agent_allows(cfg(ws)["permissions"])
    assert denied(cfg(ws)["permissions"], "opencode *")
    code, out = run(GATE, ["allow-agent", "--workspace", str(ws), "--agent", "claude-code:opus", "--quote",
                           "use claude opus as the reviewer", "--source", "chat", "--answers", str(other_agent_answers(tmp_path))], tmp_path)
    assert code == 0, out
    assert allowed(cfg(ws)["permissions"], "claude * --model opus *") and not allowed(cfg(ws)["permissions"], "claude *")


def test_missing_sidecar_does_not_duplicate_rules(tmp_path):
    ra_forge.merge_opencode_permissions(tmp_path, ["opencode"])
    once = cfg(tmp_path)["permissions"]
    (tmp_path / ".opencode" / ".ra_rules.json").unlink()
    ra_forge.merge_opencode_permissions(tmp_path, ["opencode"])
    assert cfg(tmp_path)["permissions"] == once
    (tmp_path / ".opencode" / ".ra_rules.json").write_text("{corrupt", encoding="utf-8")
    ra_forge.merge_opencode_permissions(tmp_path, [])
    rules = cfg(tmp_path)["permissions"]
    assert sum(r == {"action": "shell", "resource": "rm *", "effect": "deny"} for r in rules) == 1
    assert not agent_allows(rules)


def test_missing_sidecar_keeps_user_rules(tmp_path):
    (tmp_path / ".opencode").mkdir()
    mine = [{"action": "shell", "resource": "make *", "effect": "allow"}]
    (tmp_path / ".opencode" / "opencode.jsonc").write_text(json.dumps({"permissions": mine}), encoding="utf-8")
    ra_forge.merge_opencode_permissions(tmp_path, [])
    (tmp_path / ".opencode" / ".ra_rules.json").unlink()
    ra_forge.merge_opencode_permissions(tmp_path, [])
    rules = cfg(tmp_path)["permissions"]
    assert rules[0] == mine[0] and sum(r["resource"] == "rm *" for r in rules) == 1


def test_crash_between_sidecar_and_config_does_not_duplicate(tmp_path, monkeypatch):
    ra_forge.merge_opencode_permissions(tmp_path, ["opencode"])
    real = ra_forge._atomic_write_text
    calls = []

    def boom(path, text):
        calls.append(path.name)
        if path.name == "opencode.jsonc":
            raise OSError("crash")
        real(path, text)

    monkeypatch.setattr(ra_forge, "_atomic_write_text", boom)
    with pytest.raises(OSError):
        ra_forge.merge_opencode_permissions(tmp_path, [])
    monkeypatch.setattr(ra_forge, "_atomic_write_text", real)
    ra_forge.merge_opencode_permissions(tmp_path, [])
    rules = cfg(tmp_path)["permissions"]
    assert sum(r["resource"] == "rm *" for r in rules) == 1
    assert not agent_allows(rules)


def test_revoke_with_broken_config_warns_and_retry_works(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert run(GATE, ["init", "--workspace", str(ws)], tmp_path)[0] == 0
    run(GATE, ["allow-agent", "--workspace", str(ws), "--agent", AGENT, "--quote", QUOTE, "--source", "chat", "--answers", str(other_agent_answers(tmp_path))], tmp_path)
    ra_forge.merge_opencode_permissions(ws, rc.granted_harnesses(ws))
    f = ws / ".opencode" / "opencode.jsonc"
    good = f.read_text(encoding="utf-8")
    f.write_text("// my note\n" + good, encoding="utf-8")
    code, out = run(GATE, ["revoke-agent", "--workspace", str(ws), "--agent", AGENT], tmp_path)
    assert code == 0 and "Revoked" in out
    assert "WARNING" in out and "allow opencode *" in out and "opencode-rules" in out
    code, out = run(GATE, ["opencode-rules", "--workspace", str(ws)], tmp_path)
    assert code == 1 and "WARNING" in out
    f.write_text(good, encoding="utf-8")
    code, out = run(GATE, ["opencode-rules", "--workspace", str(ws)], tmp_path)
    assert code == 0, out
    assert not allowed(cfg(ws)["permissions"], "opencode *")


def test_allow_with_broken_config_still_grants_and_warns(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert run(GATE, ["init", "--workspace", str(ws)], tmp_path)[0] == 0
    ra_forge.merge_opencode_permissions(ws, [])
    f = ws / ".opencode" / "opencode.jsonc"
    f.write_text("// c\n" + f.read_text(encoding="utf-8"), encoding="utf-8")
    code, out = run(GATE, ["allow-agent", "--workspace", str(ws), "--agent", AGENT, "--quote", QUOTE, "--source", "chat", "--answers", str(other_agent_answers(tmp_path))], tmp_path)
    assert code == 0 and "Granted" in out and "WARNING" in out


def test_opencode_rules_command_without_rules_is_noop(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert run(GATE, ["init", "--workspace", str(ws)], tmp_path)[0] == 0
    code, out = run(GATE, ["opencode-rules", "--workspace", str(ws)], tmp_path)
    assert code == 0 and not (ws / ".opencode").exists()
