"""Fix wave 2 (v1.6): Fable's live review with Qwen. One section per item in fix-wave-2-findings.md."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ra_common as rc  # noqa: E402
import ra_forge  # noqa: E402
import ra_hooks  # noqa: E402
from test_fix_wave import REVIEW_FOCUS_PASS, oc_effect, oc_matches  # noqa: E402

GATE = ROOT / "scripts" / "ra_gate.py"
HOOKS = ROOT / "scripts" / "ra_hooks.py"
HARNESS = ROOT / "scripts" / "ra_context_harness.py"
FORGE = ROOT / "scripts" / "ra_forge.py"
HARNESS_VARS = ("OPENCODE", "OPENCODE_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                "CODEX_HOME", "CODEX_SANDBOX", "CODEX_SESSION_ID", "ANTIGRAVITY_CLI", "GEMINI_CLI", "XDG_DATA_HOME",
                "CLAUDE_PROJECT_DIR", "CLAUDE_CONFIG_DIR", "RA_WORKER")
QWEN_AGENT = "opencode:llamacpp/qwen3.8-flash-next"
KANO_QUOTE = "use qwen 3.8 from opencode for test"
QWEN_SENTENCE = ("Get an independent second opinion on it from a different AI model than yourself, "
                 "then record what it said.")
QWEN = {"id": "qwen3.8-flash-next", "providerID": "llamacpp"}
TERRA = {"id": "openai/gpt-6.1-terra-pro", "providerID": "openrouter"}
DEEPSEEK = {"id": "deepseek-v4.1-flash-free", "providerID": "opencode", "variant": "default"}
OTHER_AGENT_ANSWERS = (
    "1. The user said in chat today, in their own words, which agent to use ({n}).\n"
    "2. The task needs a second model for the cold review; I cannot do that myself.\n"
    "3. It may read research/ and write only research/sandbox/H001/.\n"
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


def make_ws(tmp_path, env=None):
    w = tmp_path / "ws"
    w.mkdir()
    assert run(GATE, ["init", "--workspace", str(w)], env or env_for(tmp_path), tmp_path)[0] == 0
    return w


@pytest.fixture
def ws(tmp_path):
    return make_ws(tmp_path)


def answers(ws):
    adir = ws / "research" / "answers"
    adir.mkdir(exist_ok=True)
    n = len(list(adir.glob("before-other-agent_*.md"))) + 1
    f = adir / f"before-other-agent_{n}.md"
    f.write_text(OTHER_AGENT_ANSWERS.format(n=n), encoding="utf-8")
    return f


def allow(tmp_path, ws, agent, quote, env=None):
    return run(GATE, ["allow-agent", "--workspace", str(ws), "--agent", agent, "--quote", quote, "--source", "chat",
                      "--answers", str(answers(ws))], env or env_for(tmp_path), tmp_path)


def make_oc_db(tmp_path, sessions, messages=()):
    """sessions: (id, parent_id, model dict or None); messages: (session_id, seq, type, model dict)."""
    d = tmp_path / "xdg" / "opencode"
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(d / "opencode.db")
    con.execute("create table session_v2(id text primary key, parent_id text, agent text, model text, time_created integer)")
    con.execute("create table session_message(id text primary key, session_id text, type text, seq integer, "
                "time_created integer, time_updated integer, data text)")
    for i, (sid, parent, model) in enumerate(sessions):
        con.execute("insert into session_v2 values (?,?,?,?,?)", (sid, parent, "build", json.dumps(model) if model else None, i))
    for i, (sid, seq, typ, model) in enumerate(messages):
        data = {"agent": "build", "content": []}
        if model:
            data["model"] = model
        con.execute("insert into session_message values (?,?,?,?,?,?,?)", (f"msg{i}", sid, typ, seq, i, i, json.dumps(data)))
    con.commit()
    con.close()
    return tmp_path / "xdg"


def oc_env(tmp_path, xdg, sid="ses_main", **extra):
    return env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID=sid, XDG_DATA_HOME=str(xdg), **extra)


def oc_identity_env(xdg, sid="ses_main", **extra):
    return {"OPENCODE": "1", "OPENCODE_SESSION_ID": sid, "XDG_DATA_HOME": str(xdg), "USERPROFILE": str(xdg),
            "HOME": str(xdg), **extra}


# ---------------------------------------------------------------- C1(a). the quote must name the agent


@pytest.mark.parametrize("quote,agent,ok", [
    (KANO_QUOTE, QWEN_AGENT, True),
    ("to use opencode qwen 3.8 flash as one of your subagent", QWEN_AGENT, True),
    ("Use QWEN3.8-flash-next via OpenCode", QWEN_AGENT, True),
    ("use flash next on opencode", QWEN_AGENT, False),  # tier words only: ask, don't guess
    ("use the qwen flash next on opencode", QWEN_AGENT, True),
    (QWEN_SENTENCE, "opencode:openrouter/openai/gpt-6.1-terra-pro", False),
    (QWEN_SENTENCE, "opencode:opencode/deepseek-v4.1-flash-free", False),
    ("use opencode for a second opinion", "opencode:openrouter/openai/gpt-6.1-terra-pro", False),
    ("use the next model in opencode", QWEN_AGENT, False),
    ("use qwen for the test", QWEN_AGENT, False),
    ("ask gpt 6.1 on opencode for a second opinion", "opencode:openrouter/openai/gpt-6.1-terra-pro", True),
    ("use deepseek from opencode", "opencode:opencode/deepseek-v4.1-flash-free", True),
    ("let claude opus review it", "claude-code:claude-opus-5-5", True),
    ("use claude code for the review", "claude-code:claude-opus-5-5", False),
    ("fable in claude code can check it", "claude-code:claude-fable-5-2", True),
    ("sonnet via claude please", "claude-code:claude-sonnet-5", True),
    ("use codex for the review work please", "codex", False),  # harness-wide needs "any model" words (R1)
    ("use codex with any model for the review", "codex", True),
    ("run it in opencode with another model", "opencode", False),
    ("use opencode", "opencode", False),
    ("use opencode with any model", "opencode", True),
    ("every opencode model is fine", "opencode", True),
    ("use whatever model opencode has", "opencode", True),
    ("use all of the models in opencode", "opencode", True),
    ("any opencode run is fine, the model too", "opencode", False),
    ("use codex for the review work please", "codex:gpt-5", False),
    ("use codex gpt-5 for the review", "codex:gpt-5", True),
    ("use gemini 3 pro in antigravity", "agy:gemini-3-pro", True),
    ("use opencode y as a worker please", "opencode:x/y", True),
    ("use opencode as a worker please", "opencode:x/y", False),
])
def test_quote_names_agent(quote, agent, ok):
    assert rc.quote_names_agent(quote, agent) is ok, (quote, agent)


def test_kano_grant_passes_and_qwen_self_grant_is_refused(tmp_path, ws):
    code, out, err = allow(tmp_path, ws, "opencode:openrouter/openai/gpt-6.1-terra-pro", QWEN_SENTENCE)
    assert code == 1
    assert "the user has not named this agent in their words; ask the user, don't grant it yourself." in err
    assert not (ws / "research" / "AGENT_PERMISSIONS.json").exists()
    code, out, err = allow(tmp_path, ws, QWEN_AGENT, KANO_QUOTE)
    assert code == 0, out + err
    assert rc.is_agent_allowed(ws, QWEN_AGENT, own_harness="")


# ---------------------------------------------------------------- C1(b). a sub-agent on another model is another agent


def test_docs_say_native_tool_is_free_only_on_own_model():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "free only on your own model" in skill and "model=" in skill
    assert "Rule: a sub-agent on another model is another agent" in skill
    assert "gpt-6.1-terra-pro" in skill  # the worked example from scenario 5
    assert "always works" not in skill
    for moment in ("worker-dispatch", "session-start"):
        body = rc.load_injection(moment)["body"]
        assert "model=" in body, moment
        assert "tools.opencode.models" in body and "opencode models" in body, moment


# ---------------------------------------------------------------- C1(c). model catalogue denied on OpenCode


def test_opencode_rules_deny_model_catalogue():
    for granted in ([], ["opencode"], [QWEN_AGENT]):
        rules = ra_forge.build_opencode_rules(granted)
        assert {"action": "opencode_models", "resource": "*", "effect": "deny"} in rules


# ---------------------------------------------------------------- C1(d). detective control for sub-agent models


def five_session_db(tmp_path):
    return make_oc_db(tmp_path, [
        ("ses_main", None, None),             # plain `opencode run`: model only in session_message
        ("ses_terra", "ses_main", TERRA),     # subagent model=... fills session_v2.model
        ("ses_deep", "ses_main", None),       # NULL: newest assistant row says deepseek
        ("ses_own", "ses_main", QWEN),        # native sub-agent on the manager's own model
        ("ses_grand", "ses_own", TERRA),      # a worker's own sub-agent
        ("ses_other", None, TERRA),           # someone else's session: not ours
    ], [
        ("ses_main", 1, "user", None), ("ses_main", 2, "assistant", QWEN),
        ("ses_deep", 1, "assistant", QWEN), ("ses_deep", 3, "assistant", DEEPSEEK), ("ses_deep", 4, "user", None),
    ])


def test_child_models_from_db(tmp_path):
    xdg = five_session_db(tmp_path)
    kids = dict((sid, m) for sid, m in rc.opencode_child_models(oc_identity_env(xdg)))
    assert kids == {"ses_terra": "openrouter/openai/gpt-6.1-terra-pro", "ses_deep": "opencode/deepseek-v4.1-flash-free",
                    "ses_own": "llamacpp/qwen3.8-flash-next", "ses_grand": "openrouter/openai/gpt-6.1-terra-pro"}
    assert rc.opencode_child_models({"OPENCODE": "1"}) == []
    assert rc.opencode_child_models(oc_identity_env(tmp_path / "nothing")) == []


@pytest.mark.parametrize("cmd", [["status"], ["board"], ["resume"]])
def test_unapproved_model_flagged_once(tmp_path, cmd):
    xdg = five_session_db(tmp_path)
    env = oc_env(tmp_path, xdg)
    w = make_ws(tmp_path, env)
    code, out, err = run(GATE, [*cmd, "--workspace", str(w)], env, tmp_path)
    assert code == 0, out + err
    assert "[RA] UNAPPROVED MODEL USED: openrouter/openai/gpt-6.1-terra-pro in sub-session ses_terra" in out
    assert "[RA] UNAPPROVED MODEL USED: opencode/deepseek-v4.1-flash-free in sub-session ses_deep" in out
    assert "[RA] UNAPPROVED MODEL USED: openrouter/openai/gpt-6.1-terra-pro in sub-session ses_grand" in out
    assert "ses_own" not in out and "ses_other" not in out
    log = (w / "research" / "LAB_LOG.md").read_text(encoding="utf-8")
    assert log.count("ses_terra") == 1 and log.count("ses_deep") == 1 and "UNAPPROVED MODEL" in log
    # Printed again on the next run, but recorded only once.
    code, out, err = run(GATE, [*cmd, "--workspace", str(w)], env, tmp_path)
    assert "UNAPPROVED MODEL USED: openrouter/openai/gpt-6.1-terra-pro in sub-session ses_terra" in out
    assert (w / "research" / "LAB_LOG.md").read_text(encoding="utf-8").count("ses_terra") == 1


def test_granted_model_is_not_flagged(tmp_path):
    xdg = five_session_db(tmp_path)
    env = oc_env(tmp_path, xdg)
    w = make_ws(tmp_path, env)
    rc.grant_agent(w, "opencode:opencode/deepseek-v4.1-flash-free", "use deepseek from opencode", "chat")
    out = run(GATE, ["status", "--workspace", str(w)], env, tmp_path)[1]
    assert "ses_deep" not in out and "ses_terra" in out
    rc.grant_agent(w, "opencode", "use any opencode model you like", "chat")
    out = run(GATE, ["board", "--workspace", str(w)], env, tmp_path)[1]
    assert "UNAPPROVED MODEL" not in out


def test_no_opencode_no_check(tmp_path, ws):
    code, out, err = run(GATE, ["status", "--workspace", str(ws)], env_for(tmp_path), tmp_path)
    assert code == 0 and "UNAPPROVED MODEL" not in out


# ---------------------------------------------------------------- I1. identity on a plain `opencode run`


def test_identity_from_newest_assistant_row(tmp_path):
    xdg = make_oc_db(tmp_path, [("ses_main", None, None)],
                     [("ses_main", 1, "user", None), ("ses_main", 2, "assistant", TERRA),
                      ("ses_main", 5, "assistant", QWEN), ("ses_main", 6, "user", None)])
    r = rc.resolve_identity(oc_identity_env(xdg))
    assert r["agent"] == QWEN_AGENT and r["source"] == "opencode-db" and r["is_subagent"] is False


def test_identity_subagent_null_model_from_messages(tmp_path):
    xdg = make_oc_db(tmp_path, [("ses_main", None, QWEN), ("ses_kid", "ses_main", None)],
                     [("ses_kid", 1, "assistant", DEEPSEEK)])
    r = rc.resolve_identity(oc_identity_env(xdg, "ses_kid"))
    assert r["agent"] == "opencode:opencode/deepseek-v4.1-flash-free" and r["is_subagent"] is True


def test_identity_null_model_no_messages_is_unknown(tmp_path):
    xdg = make_oc_db(tmp_path, [("ses_main", None, None)], [("ses_main", 1, "user", None)])
    assert rc.resolve_identity(oc_identity_env(xdg))["agent"] == "opencode:unknown"
    d = tmp_path / "old" / "opencode"
    d.mkdir(parents=True)
    con = sqlite3.connect(d / "opencode.db")  # no session_message table at all
    con.execute("create table session_v2(id text, parent_id text, model text)")
    con.execute("insert into session_v2 values ('ses_main', NULL, NULL)")
    con.commit()
    con.close()
    assert rc.resolve_identity(oc_identity_env(tmp_path / "old"))["agent"] == "opencode:unknown"


def test_decide_records_model_from_messages(tmp_path):
    xdg = make_oc_db(tmp_path, [("ses_main", None, None)], [("ses_main", 2, "assistant", QWEN)])
    env = oc_env(tmp_path, xdg)
    w = make_ws(tmp_path, env)
    code, out, err = run(GATE, ["decide", "--workspace", str(w), "--what", "score with F1 on the holdout split",
                                "--why", "the fault class is rare so accuracy hides misses", "--agent", QWEN_AGENT],
                         env, tmp_path)
    assert code == 0, out + err
    assert "You wrote --agent" not in err
    assert f"`{QWEN_AGENT}`" in (w / "research" / "DECISIONS.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- I2. tell agents about the door


def test_fork_brief_names_the_door(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    w = make_ws(tmp_path, env)
    assert run(HARNESS, ["create", "--workspace", str(w), "--id", "base", "--tier", "workflow_slice",
                         "--summary", "shared"], env, tmp_path)[0] == 0
    code, out, err = run(HARNESS, ["fork", "--workspace", str(w), "--subagent", "Worker_A", "--snapshots", "base",
                                   "--task", "clear out research/sandbox/zscore_old"], env, tmp_path)
    assert code == 0, out + err
    brief = (w / "research" / "context_snapshots" / "forks" / "FORK_Worker_A.md").read_text(encoding="utf-8")
    for line in rc.DELETE_DOOR_LINES:
        assert line in brief, line
    assert "ra_gate.py remove" in brief and "Permission denied" in brief and "conclude" in brief


def forge(tmp_path, w):
    return run(FORGE, ["--workspace", str(w), "--name", "probe", "--domain", "tests"], env_for(tmp_path), tmp_path)


def test_forge_writes_door_into_skill_and_agents_md(tmp_path, ws):
    (ws / "AGENTS.md").write_text("# My rules\n\nUse tabs.\n", encoding="utf-8")
    code, out, err = forge(tmp_path, ws)
    assert code == 0, out + err
    skill = (ws / ".agents" / "skills" / "probe-rd" / "SKILL.md").read_text(encoding="utf-8")
    agents = (ws / "AGENTS.md").read_text(encoding="utf-8")
    for line in rc.DELETE_DOOR_LINES:
        assert line in skill and line in agents, line
    assert agents.startswith("# My rules\n\nUse tabs.\n")
    assert (ROOT / "scripts" / "ra_gate.py").as_posix() in agents  # the full path: the skill may not be loaded
    code, out, err = forge(tmp_path, ws)
    assert code == 0, out + err
    again = (ws / "AGENTS.md").read_text(encoding="utf-8")
    assert again.count(ra_forge.AGENTS_BEGIN) == 1 and again.count(ra_forge.AGENTS_END) == 1
    assert again.startswith("# My rules\n\nUse tabs.\n")


def test_forge_creates_agents_md(tmp_path, ws):
    assert forge(tmp_path, ws)[0] == 0
    text = (ws / "AGENTS.md").read_text(encoding="utf-8")
    assert ra_forge.AGENTS_BEGIN in text and "ra_gate.py" in text


MOVE_ONE_LINERS = [
    "python -c \"import shutil; shutil.move('research/sandbox/zscore_old', 'research/graveyard/zscore_old')\"",
    "python3 -c \"import os;os.rename('a','b')\"",
    "python -c \"import os; os.replace('a', 'b')\"",
    "py -c \"import shutil;shutil.move(src, dst)\"",
]


@pytest.mark.parametrize("cmd", MOVE_ONE_LINERS)
def test_opencode_denies_move_one_liners(cmd):
    for granted in ([], ["opencode", "claude-code", "codex", "agy"], [QWEN_AGENT]):
        assert oc_effect(ra_forge.build_opencode_rules(granted), cmd) == "deny", (cmd, granted)


def test_move_one_liner_rules_skip_review_focus_pass_list():
    rules = ra_forge.build_opencode_rules([])
    new = [r for r in rules if any(w in r["resource"] for w in ("shutil.move", "os.rename", "os.replace", "renameSync"))]
    assert new
    bad = [(c, r["resource"]) for c in REVIEW_FOCUS_PASS for r in new + ra_forge._rules_head()
           if r["effect"] == "deny" and oc_matches(r["resource"], c)]
    assert not bad, bad
    assert oc_effect(rules, "python -c \"print('a'.replace('a', 'b'))\"") is None


def test_hook_classifies_move_one_liners():
    hits = ra_hooks.shell_safety("python -c \"import shutil; shutil.move('research/DECISIONS.md', '../D.md')\"")
    assert hits == [("move", (["research/DECISIONS.md"], "../D.md"))]
    assert ra_hooks.shell_safety("python -c \"import os; os.rename('a', 'b')\"") == [("move", (["a"], "b"))]
    assert {k for k, _ in ra_hooks.shell_safety("python -c \"import os; os.replace(src, dst)\"")} == {"delete"}
    assert ra_hooks.shell_safety("python -c \"print('a'.replace('a', 'b'))\"") == []
    for cmd in REVIEW_FOCUS_PASS:
        assert ra_hooks.shell_safety(cmd) == [], cmd


def hook(tmp_path, w, command):
    payload = {"cwd": str(w), "tool_name": "Bash", "tool_input": {"command": command}, "session_id": "s1"}
    code, out, err = run(HOOKS, ["pre-tool"], env_for(tmp_path), tmp_path, json.dumps(payload).encode())
    return code, err


def test_hook_move_one_liner_uses_mv_logic(tmp_path, ws):
    code, err = hook(tmp_path, ws, "python -c \"import shutil; shutil.move('research/DECISIONS.md', '../D.md')\"")
    assert code == 2 and "Move blocked" in err
    code, err = hook(tmp_path, ws, "python -c \"import os; os.rename('research/sandbox/a', 'research/sandbox/b')\"")
    assert code == 0, err


# ---------------------------------------------------------------- I3. a model grant covers that model only


def test_model_grant_rules_carry_the_model():
    rules = ra_forge.build_opencode_rules([QWEN_AGENT])
    for cmd in ("opencode run -m llamacpp/qwen3.8-flash-next \"x\"", "opencode run --model llamacpp/qwen3.8-flash-next x",
                'opencode run --title W --model "llamacpp/qwen3.8-flash-next" --auto -f "a.md" "go"',
                "opencode run -m=llamacpp/qwen3.8-flash-next x", "opencode run x -m llamacpp/qwen3.8-flash-next",
                r"C:\npm\opencode.cmd run -m llamacpp/qwen3.8-flash-next x"):
        assert oc_effect(rules, cmd) == "allow", cmd
    for cmd in ("opencode run x", "opencode run -m openrouter/openai/gpt-6.1-terra-pro x",
                "opencode run -m llamacpp/qwen3.8-flash-next-evil x", "opencode models", "claude -p x",
                'bash -c "opencode run -m llamacpp/qwen3.8-flash-next x; rm -rf y"', "opencode models -m llamacpp/qwen3.8-flash-next",
                "RA_WORKER=W opencode run x", "FOO=1 opencode run -m llamacpp/qwen3.8-flash-next x", "X=1 rm -rf y"):
        assert oc_effect(rules, cmd) == "deny", cmd
    assert not any(r["resource"] == "opencode *" and r["effect"] == "allow" for r in rules)
    assert oc_effect(ra_forge.build_opencode_rules(["opencode"]), "opencode run x") == "allow"


def test_model_grant_block_found_without_sidecar(tmp_path):
    ra_forge.merge_opencode_permissions(tmp_path, ["opencode", QWEN_AGENT, "claude-code:opus"])
    (tmp_path / ".opencode" / ".ra_rules.json").unlink()
    assert ra_forge.opencode_rules_present(tmp_path)
    ra_forge.merge_opencode_permissions(tmp_path, [])
    rules = json.loads((tmp_path / ".opencode" / "opencode.jsonc").read_text(encoding="utf-8"))["permissions"]
    assert rules == ra_forge.build_opencode_rules([])


def test_is_agent_allowed_matches_model(tmp_path):
    w = tmp_path / "w"
    rc.grant_agent(w, QWEN_AGENT, KANO_QUOTE, "chat")
    assert rc.is_agent_allowed(w, QWEN_AGENT, own_harness="")
    assert rc.is_agent_allowed(w, "opencode:LlamaCpp/Qwen3.8-Flash-Next", own_harness="")
    assert not rc.is_agent_allowed(w, "opencode", own_harness="")  # no -m = the default model, could be anything
    assert not rc.is_agent_allowed(w, "opencode:openrouter/openai/gpt-6.1-terra-pro", own_harness="")
    rc.grant_agent(w, "opencode", "use any opencode model you like", "chat")
    assert rc.is_agent_allowed(w, "opencode", own_harness="")
    assert rc.is_agent_allowed(w, "opencode:openrouter/openai/gpt-6.1-terra-pro", own_harness="")
    assert rc.granted_agents(w) == [QWEN_AGENT, "opencode"]


def test_claude_hook_compares_model_flag(tmp_path, ws):
    rc.grant_agent(ws, QWEN_AGENT, KANO_QUOTE, "chat")
    assert hook(tmp_path, ws, 'opencode run -m llamacpp/qwen3.8-flash-next "x"')[0] == 0
    assert hook(tmp_path, ws, 'opencode run --model "llamacpp/qwen3.8-flash-next" "x"')[0] == 0
    code, err = hook(tmp_path, ws, 'opencode run "x"')
    assert code == 2 and "Other agent blocked" in err
    assert hook(tmp_path, ws, "opencode run --model openrouter/openai/gpt-6.1-terra-pro x")[0] == 2
    assert hook(tmp_path, ws, "claude -p x")[0] == 2


def test_fork_prints_cli_with_granted_model(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    w = make_ws(tmp_path, env)
    assert run(HARNESS, ["create", "--workspace", str(w), "--id", "base", "--tier", "workflow_slice",
                         "--summary", "shared"], env, tmp_path)[0] == 0
    rc.grant_agent(w, QWEN_AGENT, KANO_QUOTE, "chat")
    rc.grant_agent(w, "codex:gpt-5", "use codex gpt-5 for the review", "chat")
    code, out, err = run(HARNESS, ["fork", "--workspace", str(w), "--subagent", "Worker_A", "--snapshots", "base",
                                   "--task", "x", "--platform", "codex"], env, tmp_path)
    assert code == 0, out + err
    assert '--model "llamacpp/qwen3.8-flash-next"' in out
    assert 'codex exec' in out and '-m "gpt-5"' in out
    rules = ra_forge.build_opencode_rules(rc.granted_agents(w))
    cli = next(ln for ln in out.splitlines() if "opencode run" in ln and "RA_WORKER=" in ln)
    oc_cmd = cli[cli.index("opencode run"):]
    assert oc_effect(rules, oc_cmd) == "allow", oc_cmd
    # A model the grant doesn't name is refused for another harness.
    code, out, err = run(HARNESS, ["fork", "--workspace", str(w), "--subagent", "Worker_B", "--snapshots", "base",
                                   "--task", "x", "--platform", "codex", "--model", "o9", "--parallel"], env, tmp_path)
    assert code == 1 and "o9" in out + err


def test_allow_agent_states_what_it_covers(tmp_path, ws):
    code, out, err = allow(tmp_path, ws, QWEN_AGENT, KANO_QUOTE)
    assert code == 0, out + err
    assert "Covers:" in out and "-m llamacpp/qwen3.8-flash-next" in out
    assert "Not covered:" in out and "without -m" in out
    code, out, err = allow(tmp_path, ws, "codex", "use codex with any model you need")
    assert code == 0, out + err
    assert "every codex model" in out


# ---------------------------------------------------------------- I5. CLI workers count as workers


def test_ra_worker_env_makes_a_worker(tmp_path):
    xdg = make_oc_db(tmp_path, [("ses_cli", None, QWEN)])
    r = rc.resolve_identity(oc_identity_env(xdg, "ses_cli", RA_WORKER="Worker_A"))
    assert r["is_subagent"] is True and r["worker"] == "Worker_A" and r["agent"] == QWEN_AGENT
    assert rc.resolve_identity(oc_identity_env(xdg, "ses_cli"))["is_subagent"] is False
    assert rc.resolve_identity({"RA_WORKER": "W"})["is_subagent"] is True


def test_remove_refuses_ra_worker(tmp_path, ws):
    f = ws / "research" / "sandbox" / "tmp.txt"
    f.write_text("x", encoding="utf-8")
    adir = ws / "research" / "answers"
    adir.mkdir(exist_ok=True)
    (adir / "before-delete_1.md").write_text(
        "1. research/sandbox/tmp.txt is inside research/sandbox; I created it this session.\n"
        "2. Nothing depends on it; grep -rn found no references to it.\n"
        "3. It is not the user's data, it is my scratch output.\n4. Recoverable from research/.trash.\n", encoding="utf-8")
    code, out, err = run(GATE, ["remove", "--workspace", str(ws), "--path", str(f), "--answers",
                                str(adir / "before-delete_1.md")], env_for(tmp_path, RA_WORKER="Worker_A"), tmp_path)
    assert code == 1 and "workers cannot remove" in err and f.exists()


def test_fork_cli_sets_ra_worker(tmp_path):
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_main")
    w = make_ws(tmp_path, env)
    assert run(HARNESS, ["create", "--workspace", str(w), "--id", "base", "--tier", "workflow_slice",
                         "--summary", "shared"], env, tmp_path)[0] == 0
    rc.grant_agent(w, QWEN_AGENT, KANO_QUOTE, "chat")
    code, out, err = run(HARNESS, ["fork", "--workspace", str(w), "--subagent", "Worker_A", "--snapshots", "base",
                                   "--task", "x"], env, tmp_path)
    assert code == 0, out + err
    assert "RA_WORKER=Worker_A opencode run" in out  # bash: this command only
    assert "$env:RA_WORKER='Worker_A'; try { opencode run" in out and "finally { $env:RA_WORKER=$null }" in out
    assert "Remove-Item" not in out
    # The Claude hook still sees the launch inside the PowerShell form, and its model.
    ps = next(ln for ln in out.splitlines() if "PowerShell:" in ln and "opencode run" in ln).split("PowerShell: ", 1)[1]
    assert ("agent-launch", "opencode:llamacpp/qwen3.8-flash-next") in ra_hooks.shell_safety(ps)
    assert ("agent-launch", "claude") in ra_hooks.shell_safety("try { claude -p x } finally { $x=1 }")


# ---------------------------------------------------------------- minors


def test_m1_allow_agent_no_false_warning_and_records_grantor(tmp_path):
    xdg = make_oc_db(tmp_path, [("ses_main", None, QWEN)])
    env = oc_env(tmp_path, xdg)
    w = make_ws(tmp_path, env)
    code, out, err = allow(tmp_path, w, "opencode:opencode/deepseek-v4.1-flash-free", "use deepseek from opencode", env)
    assert code == 0, out + err
    assert "You wrote --agent" not in out + err
    grant = json.loads((w / "research" / "AGENT_PERMISSIONS.json").read_text(encoding="utf-8"))["allow"][0]
    assert grant["agent"] == "opencode:opencode/deepseek-v4.1-flash-free" and grant["granted_by"] == QWEN_AGENT
    assert f"recorded by `{QWEN_AGENT}`" in out


def test_m2_state_version_from_one_constant(tmp_path, ws):
    assert rc.RA_VERSION == "1.6.0"
    assert json.loads((ws / "research" / ".ra_state.json").read_text(encoding="utf-8"))["version"] == rc.RA_VERSION
    assert '"1.5.0"' not in (ROOT / "scripts" / "ra_gate.py").read_text(encoding="utf-8")


def test_m3_init_prints_session_start(tmp_path):
    w = tmp_path / "w"
    w.mkdir()
    code, out, err = run(GATE, ["init", "--workspace", str(w)], env_for(tmp_path), tmp_path)
    assert code == 0 and "# Session start" in out and "You are: unknown" in out


def test_m5_no_opencode_discovery(tmp_path, monkeypatch):
    import ra_context_harness as h
    src = (ROOT / "scripts" / "ra_context_harness.py").read_text(encoding="utf-8")
    assert "shutil.which" not in src and "session\", \"list" not in src

    def boom(*a, **k):
        raise AssertionError("subprocess used")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    assert h.auto_discover_native_session_id(tmp_path, "opencode") is None
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_env")
    assert h.auto_discover_native_session_id(tmp_path, "opencode") == "ses_env"


def test_m7_protected_names_listed(tmp_path):
    code, out, err = run(GATE, ["remove", "--help"], env_for(tmp_path), tmp_path)
    assert code == 0
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    for name in rc.PROTECTED_NAMES + tuple(f"research/{d}/" for d in rc.PROTECTED_DIRS):
        assert name in out, name
        assert name in skill, name
    assert "REPORT.md" in out and "REPORT.md" in skill


# ---------------------------------------------------------------- round 2, R1. harness-wide grants need "any model" words


@pytest.mark.parametrize("quote", ["run it in opencode with another model", "use opencode"])
def test_r1_harness_wide_grant_refused_without_any_model_words(tmp_path, ws, quote):
    code, out, err = allow(tmp_path, ws, "opencode", quote)
    assert code == 1
    assert ("a grant for every opencode model needs the user's words to say so; otherwise ask the user which model."
            in err)
    assert "any model" not in err and "whatever" not in err
    assert not (ws / "research" / "AGENT_PERMISSIONS.json").exists()


def test_r1_harness_wide_grant_with_any_model_words(tmp_path, ws):
    code, out, err = allow(tmp_path, ws, "opencode", "use opencode with any model")
    assert code == 0, out + err
    assert rc.is_agent_allowed(ws, "opencode", own_harness="")
    assert "every opencode model" in out


def test_r1_model_grant_still_needs_only_the_model(tmp_path, ws):
    code, out, err = allow(tmp_path, ws, QWEN_AGENT, KANO_QUOTE)
    assert code == 0, out + err
    code, out, err = allow(tmp_path, ws, "opencode:openrouter/openai/gpt-6.1-terra-pro", "use opencode")
    assert code == 1 and "has not named this agent" in err


# ---------------------------------------------------------------- round 2, R2. `*=*` denies vs everyday searches


def oc_split(command):
    """OpenCode checks every subcommand: split on ; | & && || outside quotes (a heredoc body stays put)."""
    parts, cur, q, i = [], "", "", 0
    while i < len(command):
        ch = command[i]
        if q:
            q = "" if ch == q else q
            cur += ch
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch in ";|&" or (ch == "\n" and "<<" not in command):
            parts.append(cur)
            cur = ""
            while i + 1 < len(command) and command[i + 1] in "|&":
                i += 1
        else:
            cur += ch
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def oc_verdict(rules, command):
    effects = [oc_effect(rules, sub) for sub in oc_split(command)]
    return "deny" if "deny" in effects else ("allow" if "allow" in effects else None)


GRANT_SETS = [[], ["opencode", "claude-code", "codex", "agy"], [QWEN_AGENT, "claude-code:opus"]]
R2_PASS = ['grep -rn --include="*.md" opencode docs/', "grep --color=always claude README.md", "rg --type=py codex src",
           'git commit -m "a=b rm x"', "git log --format=%H -- research/LAB_LOG.md claude",
           'egrep --include=*.py -n "rm -rf" src', "findstr /s /i claude=1 *.md", 'Select-String -Pattern "x=1 rm" -Path *.md',
           "sls -Pattern a=b opencode", 'git grep -n "a=b" claude']
R2_DENY = ["X=1 rm -rf research", "X=1 opencode run hi", "FOO=bar claude -p hi", "grep x && rm -rf research",
           "grep x; X=1 rm y", "grep x | X=1 codex exec y", "rg x || FOO=1 rmdir research",
           "X=1 rm -rf a/opencode b -m llamacpp/qwen3.8-flash-next c",
           "RA_WORKER=a rm -rf y opencode x -m llamacpp/qwen3.8-flash-next z", "grep x && where claude",
           "grep x\nX=1 rm y"]


@pytest.mark.parametrize("granted", GRANT_SETS)
def test_r2_everyday_commands_pass(granted):
    from test_fix_wave import EVERYDAY
    rules = ra_forge.build_opencode_rules(granted)
    bad = [c for c in R2_PASS + REVIEW_FOCUS_PASS + EVERYDAY if oc_verdict(rules, c) == "deny"]
    assert not bad, bad


@pytest.mark.parametrize("granted", GRANT_SETS)
def test_r2_assignment_prefixed_deletes_and_launches_stay_denied(granted):
    rules = ra_forge.build_opencode_rules(granted)
    bad = [c for c in R2_DENY if oc_verdict(rules, c) != "deny"]
    assert not bad, bad


@pytest.mark.parametrize("granted", GRANT_SETS)
def test_r2_no_allow_reopens_a_deny(granted):
    """Every delete / move / lookup / catalogue deny, and every launch deny of a CLI with no harness-wide grant,
    instantiated (each `*` -> `a`), is still denied by the whole list."""
    rules = ra_forge.build_opencode_rules(granted)
    wide = {c for g in granted if ":" not in g for c in ra_forge.OPENCODE_HARNESS_CLIS.get(g, ())}
    bad = []
    for r in ra_forge._rules_suffix():
        if r["action"] == "shell" and r["effect"] == "deny" and oc_verdict(rules, r["resource"].replace("*", "a")) != "deny":
            bad.append(r["resource"])
    for r in ra_forge._rules_head():
        cli = next(c for c in rc.SAFETY_AGENT_CLIS if c in r["resource"])
        if (r["resource"].startswith("*=*") or cli not in wide) and oc_verdict(rules, r["resource"].replace("*", "a")) != "deny":
            bad.append(r["resource"])
    denies = [r["resource"].replace("*", "a") for r in ra_forge._rules_suffix()
              if r["action"] == "shell" and r["effect"] == "deny" and not r["resource"].startswith(("rg ", "git grep "))]
    denies += [r["resource"].replace("*", "a") for r in ra_forge._rules_head()
               if r["resource"].startswith("*=*") or next(c for c in rc.SAFETY_AGENT_CLIS if c in r["resource"]) not in wide]
    for d in denies:  # an everyday head must not let a program-running argument form past the deny
        for cmd in (f"rg --pre {d}", f"git grep -O{d}", f"grep x $({d})", f"git log `{d}`"):
            if oc_verdict(rules, cmd) != "deny":
                bad.append(cmd)
    assert not bad, bad
