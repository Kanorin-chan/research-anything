import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ra_hooks  # noqa: E402

GATE = ROOT / "scripts" / "ra_gate.py"
HOOKS = ROOT / "scripts" / "ra_hooks.py"
HARNESS_VARS = ("OPENCODE", "OPENCODE_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                "CODEX_HOME", "CODEX_SANDBOX", "CODEX_SESSION_ID", "ANTIGRAVITY_CLI", "GEMINI_CLI", "XDG_DATA_HOME",
                "CLAUDE_PROJECT_DIR")

BLOCKS = [
    ("rm -rf research/sandbox/x", "delete"),
    (r'Remove-Item -Recurse -Force "F:\My Project\research\sandbox\x"', "delete"),
    ("git clean -fdx", "delete"),
    ("git reset --hard HEAD~1", "delete"),
    ("git checkout -- src/a.py", "delete"),
    ("git restore src/a.py", "delete"),
    ("find . -name '*.tmp' -delete", "delete"),
    ("ls | xargs rm", "delete"),
    ('python -c "import shutil;shutil.rmtree(\'x\')"', "delete"),
    ("node -e \"require('fs').rmSync('x',{recursive:true})\"", "delete"),
    ("del /f /q x.txt", "delete"),
    ("echo hi; rm x", "delete"),
    ("sudo rm -r x", "delete"),
    ("cd x && rmdir y", "delete"),
    (r"C:\Users\me\AppData\Roaming\npm\claude.cmd -p hi", "agent-launch"),
    ("npx opencode run x", "agent-launch"),
    ('pwsh -c "codex exec y"', "agent-launch"),
    ('powershell -NoProfile -Command "agy chat"', "agent-launch"),
    ('cmd /c "gemini -p hi"', "agent-launch"),
    ('bash -c "claude -p x"', "agent-launch"),
    ('start "" antigravity', "agent-launch"),
    (r'& "C:\x\opencode.exe" run z', "agent-launch"),
    ("claude", "agent-launch"),
    ("where claude", "agent-lookup"),
    ("Get-Command agy", "agent-lookup"),
    ("which opencode", "agent-lookup"),
    ("command -v codex", "agent-lookup"),
    (r"ls C:\Users\x\AppData\Roaming\npm\node_modules\@anthropic-ai", "agent-lookup"),
    ("dir ~/.codex", "agent-lookup"),
]

PASSES = [
    "git status",
    "grep -rn rm src/",
    "cat claude_notes.md",
    "python claude_shim.py",
    'echo "rm -rf is dangerous"',
    "printf 'del x; rm y'",
    "Write-Host 'Remove-Item x'",
    "cat <<'EOF'\nrm -rf /\nclaude -p x\nEOF",
    "npm uninstall x",
    "git clean -n",
    "git restore --staged a.py",
    "git checkout main",
    "ls src",
    "ls ~/.gemini/skills/research-anything",
    'python -I "C:/x/scripts/ra_gate.py" remove --path a --answers b',
    "claude --version",
    "claude --help",
    "python -c \"print('hello')\"",
    "grep -rn claude src/ | head",
]



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

def kinds(cmd):
    return {k for k, _ in ra_hooks.shell_safety(cmd)}


@pytest.mark.parametrize("cmd,kind", BLOCKS)
def test_blocks(cmd, kind):
    assert kind in kinds(cmd), (cmd, ra_hooks.shell_safety(cmd))


@pytest.mark.parametrize("cmd", PASSES)
def test_passes(cmd):
    assert ra_hooks.shell_safety(cmd) == [], cmd


def test_classifier_has_no_subprocess(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess used")

    monkeypatch.setattr(subprocess, "Popen", boom)
    assert kinds("rm x") == {"delete"}
    assert kinds("claude -p x") == {"agent-launch"}
    assert kinds("git status") == set()


def env_for(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    home = str(tmp_path / "home")
    env.update({"USERPROFILE": home, "HOME": home, "PYTHONUTF8": "1"})
    return env


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    p = subprocess.run([sys.executable, "-I", str(GATE), "init", "--workspace", str(w)], capture_output=True,
                       env=env_for(tmp_path), cwd=str(tmp_path))
    assert p.returncode == 0, p.stderr
    return w


def hook(tmp_path, ws, tool, command, **extra):
    payload = {"cwd": str(ws), "tool_name": tool, "tool_input": {"command": command}, "session_id": "s1", **extra}
    p = subprocess.run([sys.executable, "-I", str(HOOKS), "pre-tool"], input=json.dumps(payload).encode(),
                       capture_output=True, env=env_for(tmp_path), cwd=str(tmp_path))
    return p.returncode, p.stderr.decode("utf-8", "replace")


def test_hook_blocks_worker_delete(tmp_path, ws):
    code, err = hook(tmp_path, ws, "Bash", "rm x", agent_id="a1")
    assert code == 2
    assert "Before delete" in err
    assert "manager removes it" in err


def test_hook_blocks_manager_delete_and_names_the_door(tmp_path, ws):
    code, err = hook(tmp_path, ws, "Bash", "rm -rf research/sandbox/x")
    assert code == 2
    assert "Before delete" in err and "ra_gate.py" in err and "remove" in err


def test_hook_powershell_delete(tmp_path, ws):
    code, err = hook(tmp_path, ws, "PowerShell", "Remove-Item -Recurse x")
    assert code == 2 and "Before delete" in err


def test_hook_gate_remove_passes_for_manager_blocks_worker(tmp_path, ws):
    cmd = 'python -I "C:/x/scripts/ra_gate.py" remove --path a --answers b'
    assert hook(tmp_path, ws, "Bash", cmd)[0] == 0
    code, err = hook(tmp_path, ws, "Bash", cmd, agent_id="a1")
    assert code == 2 and "manager removes it" in err


def test_hook_agent_launch_needs_grant(tmp_path, ws):
    code, err = hook(tmp_path, ws, "Bash", "npx opencode run x")
    assert code == 2 and "Before using another agent" in err
    p = subprocess.run([sys.executable, "-I", str(GATE), "allow-agent", "--workspace", str(ws), "--agent", "opencode",
                        "--quote", "use opencode with any model as a worker please", "--source", "test",
                        "--answers", str(other_agent_answers(tmp_path))],
                       capture_output=True, env=env_for(tmp_path), cwd=str(tmp_path))
    assert p.returncode == 0, p.stderr
    assert hook(tmp_path, ws, "Bash", "npx opencode run x")[0] == 0
    assert hook(tmp_path, ws, "Bash", "codex exec x")[0] == 2


def test_hook_claude_version_passes_but_launch_blocks(tmp_path, ws):
    assert hook(tmp_path, ws, "Bash", "claude --version")[0] == 0
    assert hook(tmp_path, ws, "Bash", "claude -p hi")[0] == 2


def test_hook_agent_lookup(tmp_path, ws):
    code, err = hook(tmp_path, ws, "Bash", "where claude")
    assert code == 2 and "searching" in err.lower()


def test_hook_powershell_write_block(tmp_path, ws):
    code, err = hook(tmp_path, ws, "PowerShell", "Set-Content -Path src/x.py -Value hi")
    assert code == 2 and "lab manager" in err
    assert hook(tmp_path, ws, "PowerShell", "Set-Content -Path research/notes.md -Value hi")[0] == 0


def test_hook_outside_ra_workspace_is_silent(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert hook(tmp_path, plain, "Bash", "rm x")[0] == 0


def test_matchers_include_powershell():
    for f in (ROOT / "SKILL.md", ROOT / "resources" / "hooks-frontmatter.yaml", ROOT / "scripts" / "ra_forge.py"):
        assert "NotebookEdit|Bash|PowerShell" in f.read_text(encoding="utf-8"), f


FIX_BLOCKS = [
    ("rm -rf x; python ra_gate.py remove --path a", "delete"),
    ("python ra_gate.py remove --path a && rm -rf b", "delete"),
    ("claude -p x; python ra_gate.py remove --path a", "agent-launch"),
    ("echo $(rm x)", "delete"),
    ("echo `rm x`", "delete"),
    ('echo "$(rm x)"', "delete"),
    ("x=$(rm -rf y)", "delete"),
    ("x=$(claude -p hi) ; echo $x", "agent-launch"),
    ('bash -lc "rm x"', "delete"),
    ('sh -ic "claude -p x"', "agent-launch"),
    (r"\rm x", "delete"),
    ('eval "rm x"', "delete"),
    ('iex "Remove-Item x"', "delete"),
    ('Invoke-Expression "codex exec y"', "agent-launch"),
    ("powershell -EncodedCommand cgBtAA==", "unclassifiable"),
    ("pwsh -enc cgBtAA==", "unclassifiable"),
    ("pwsh -e cgBtAA==", "unclassifiable"),
    (r"ls C:\Users\x\AppData\Roaming\npm", "agent-lookup"),
    ("ls ~/.config/opencode", "agent-lookup"),
    ("ls ~/.local/share/opencode", "agent-lookup"),
    (r"dir C:\Users\x\AppData\Local\Programs\Antigravity", "agent-lookup"),
    ("ls ~/.gemini/antigravity", "agent-lookup"),
]

FIX_PASSES = [
    "ls src/opencode", "ls -la gemini", "ls claude", r"dir node_modules\gemini", "ls ~/proj/gemini",
    "echo '$(rm x)'", "echo $(date)", "x=$(pwd)", 'bash -lc "git status"', "eval \"echo hi\"",
    "powershell -NoProfile -Command Get-Date", "python -I C:/x/ra_gate.py status",
    "python ra_gate.py remove --path a && git status",
]


@pytest.mark.parametrize("cmd,kind", FIX_BLOCKS)
def test_fix_blocks(cmd, kind):
    assert kind in kinds(cmd), (cmd, ra_hooks.shell_safety(cmd))


@pytest.mark.parametrize("cmd", FIX_PASSES)
def test_fix_passes(cmd):
    assert ra_hooks.shell_safety(cmd) == [], cmd


def test_worker_gate_remove_is_delete_even_chained():
    assert kinds("python ra_gate.py remove --path a") == set()
    assert ra_hooks.shell_safety("echo hi; python ra_gate.py remove --path a", worker=True) == [("delete", "")]


def test_hook_chained_gate_remove_still_blocked(tmp_path, ws):
    assert hook(tmp_path, ws, "Bash", "rm -rf x; python ra_gate.py remove --path a")[0] == 2
    code, err = hook(tmp_path, ws, "Bash", "pwsh -enc cgBtAA==")
    assert code == 2 and "encoded command" in err


R2_BLOCKS = [
    ('python -c "import shutil;shutil.rmtree(\'x\')" ra_gate.py remove', "delete"),
    ("python evil.py ra_gate.py remove", None),
    ("python -m evil ra_gate.py remove", None),
    ("echo \"it's\" $(rm x)", "delete"),
    ("echo \"don't\" `rm x`", "delete"),
    ("echo \"a'b\" \"$(rm x)\"", "delete"),
    ("cat <(rm x)", "delete"),
    ("echo hi >(rm x)", "delete"),
    ("ls /usr/local/lib/node_modules/@anthropic-ai", "agent-lookup"),
    ("ls ~/.npm-global/lib/node_modules/@anthropic-ai/claude-code", "agent-lookup"),
    ("pwsh -NoProfile -ExecutionPolicy Bypass -enc cgBtAA==", "unclassifiable"),
]


@pytest.mark.parametrize("cmd,kind", R2_BLOCKS)
def test_round2_blocks(cmd, kind):
    got = ra_hooks.shell_safety(cmd)
    if kind is None:  # not exempt: no gate-remove pass; harmless commands are simply not delete
        assert cmd.startswith("python") and ra_hooks._is_gate_remove("python", cmd.split()[1:]) is False
    else:
        assert kind in {k for k, _ in got}, (cmd, got)


@pytest.mark.parametrize("cmd", [
    "echo '$(rm x)'", 'pwsh -c "echo -e hi"', "pwsh -Command \"echo -e hi\"",
    "python -I ra_gate.py remove --path a", "python -u -X dev ra_gate.py remove --path a",
    "echo \"it's fine\" 'and $(rm x)'",
])
def test_round2_passes(cmd):
    assert ra_hooks.shell_safety(cmd) == [], cmd


R3_BLOCKS = [
    (r"echo it\'s $(rm x)", "delete"),
    ("python -Ic \"import os;os.remove('x')\"", "delete"),
    ("python -Ec \"import shutil;shutil.rmtree('x')\"", "delete"),
    (r"python -cimport\ shutil\;shutil.rmtree\(\'x\'\)", "delete"),
    ("python -c \"__import__('os').remove('x')\"", "delete"),
    ("python -c \"import pathlib;pathlib.Path('x').unlink()\"", "delete"),
    ("node -e \"require('fs').unlinkSync('x')\"", "delete"),
    ("node -p \"require('fs').rmSync('x')\"", "delete"),
    (r"node -erequire\(\'fs\'\).rmSync\(\'x\'\)", "delete"),
    ("pwsh /enc cgBtAA==", "unclassifiable"),
    ("powershell /EncodedCommand cgBtAA==", "unclassifiable"),
]


@pytest.mark.parametrize("cmd,kind", R3_BLOCKS)
def test_round3_blocks(cmd, kind):
    assert kind in kinds(cmd), (cmd, ra_hooks.shell_safety(cmd))


@pytest.mark.parametrize("cmd", [
    r"echo it\'s fine", "python -c \"print('hi')\"", "python script.py -c \"os.remove(x)\"",
    'pwsh /c "echo -e hi"', "python -m pytest -c pytest.ini tests",
])
def test_round3_passes(cmd):
    assert ra_hooks.shell_safety(cmd) == [], cmd


@pytest.mark.parametrize("cmd", ["python evil.py ra_gate.py remove", "python -m evil ra_gate.py remove"])
def test_round2_unexempt_forms_through_shell_safety(cmd):
    assert ra_hooks.shell_safety(cmd) == []
    assert ra_hooks.shell_safety(cmd, worker=True) == []  # not the door, so nothing to block either
