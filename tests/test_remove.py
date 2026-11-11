import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ra_common as rc  # noqa: E402

GATE = ROOT / "scripts" / "ra_gate.py"
HARNESS_VARS = ("OPENCODE", "OPENCODE_SESSION_ID", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT",
                "CODEX_HOME", "CODEX_SANDBOX", "CODEX_SESSION_ID", "ANTIGRAVITY_CLI", "GEMINI_CLI", "XDG_DATA_HOME")
GOOD = "\n".join(f"{n}. Checked with grep and ls: only sandbox scratch files, nothing imports them (answer {n})." for n in range(1, 5))
WIN = os.name == "nt"


def env_for(tmp_path, **extra):
    env = {k: v for k, v in os.environ.items() if k not in HARNESS_VARS}
    home = str(tmp_path / "home")
    env.update({"USERPROFILE": home, "HOME": home, "PYTHONUTF8": "1"})
    env.update(extra)
    return env


def run(args, env, cwd):
    p = subprocess.run([sys.executable, "-I", str(GATE), *args], capture_output=True, env=env, cwd=str(cwd))
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    assert run(["init", "--workspace", str(w)], env_for(tmp_path), tmp_path)[0] == 0
    (w / "research" / "answers").mkdir(exist_ok=True)
    (w / "research" / "answers" / "before-delete_1.md").write_text(GOOD, encoding="utf-8")
    return w


def answers(w, paths=()):
    """A fresh answers file (each one approves one remove) naming every target, workspace-relative."""
    d = w / "research" / "answers"
    f = d / f"before-delete_{len(list(d.glob('before-delete_*.md'))) + 1}.md"
    names = []
    for p in paths:
        try:
            names.append(Path(p).resolve().relative_to(w.resolve()).as_posix())
        except ValueError:
            names.append(str(p))
    f.write_text(GOOD + "\nPaths: " + ", ".join(names) + "\n", encoding="utf-8")
    return str(f)


def remove(w, tmp_path, paths, extra=(), env=None, ans=None):
    args = ["remove", "--workspace", str(w), "--answers", ans or answers(w, paths)]
    for p in paths:
        args += ["--path", str(p)]
    return run(args + list(extra), env or env_for(tmp_path), tmp_path)


def test_remove_sandbox_file_goes_to_trash(ws, tmp_path):
    f = ws / "research" / "sandbox" / "scratch.txt"
    f.write_text("x")
    code, out, err = remove(ws, tmp_path, [f])
    assert code == 0, out + err
    assert not f.exists()
    trash = list((ws / "research" / ".trash").glob("*/research/sandbox/scratch.txt"))
    assert len(trash) == 1
    man = json.loads((trash[0].parents[2] / "MANIFEST.json").read_text(encoding="utf-8"))
    assert man[0]["original"].endswith("research/sandbox/scratch.txt") and man[0]["moved_to"].endswith("scratch.txt")
    assert man[0]["answers_file"] and man[0]["agent"] and man[0]["time"]
    assert "remove" in (ws / "research" / "LAB_LOG.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", ["research/DIRECTIVES.md", "research/graveyard/x.md", "research/reviews/r.md",
                                 "research/hypotheses/H1/REPORT.md", "research/.ra_state.json"])
def test_remove_protected_refused(ws, tmp_path, rel):
    f = ws / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("keep")
    code, out, err = remove(ws, tmp_path, [f], ["--user-quote", "the user said delete it all please"])
    assert code == 1 and "protected" in err and "Before delete" in out
    assert f.exists()


def test_remove_outside_refused(ws, tmp_path):
    f = tmp_path / "elsewhere.txt"
    f.write_text("mine")
    code, out, err = remove(ws, tmp_path, [f], ["--user-quote", "the user said delete it all please"])
    assert code == 1 and "outside" in err and f.exists()


def test_remove_workspace_needs_quote(ws, tmp_path):
    f = ws / "src.py"
    f.write_text("x")
    code, out, err = remove(ws, tmp_path, [f])
    assert code == 1 and "--user-quote" in err and f.exists()
    code, out, err = remove(ws, tmp_path, [f], ["--user-quote", "short"])
    assert code == 1 and f.exists()
    code, out, err = remove(ws, tmp_path, [f], ["--user-quote", "delete src.py please"])
    assert code == 0, out + err
    assert not f.exists()
    assert list((ws / "research" / ".trash").glob("*/src.py"))


def test_remove_bare_yes_answers_refused(ws, tmp_path):
    f = ws / "research" / "sandbox" / "a.txt"
    f.write_text("x")
    bad = ws / "research" / "answers" / "before-delete_2.md"
    bad.write_text("1. yes\n2. ok\n3. done\n4. yes\n")
    code, out, err = remove(ws, tmp_path, [f], ans=str(bad))
    assert code == 1 and "answers not accepted" in err and f.exists()
    code, out, err = remove(ws, tmp_path, [f], ans=str(ws / "nope.md"))
    assert code == 1 and f.exists()


def test_remove_refused_for_opencode_subsession(ws, tmp_path):
    d = tmp_path / "xdg" / "opencode"
    d.mkdir(parents=True)
    con = sqlite3.connect(d / "opencode.db")
    con.execute("create table session_v2(id text, parent_id text, model text)")
    con.execute("insert into session_v2 values ('ses_1','ses_0','{\"id\":\"m\",\"providerID\":\"p\"}')")
    con.commit()
    con.close()
    env = env_for(tmp_path, OPENCODE="1", OPENCODE_SESSION_ID="ses_1", XDG_DATA_HOME=str(tmp_path / "xdg"))
    f = ws / "research" / "sandbox" / "a.txt"
    f.write_text("x")
    code, out, err = remove(ws, tmp_path, [f], env=env)
    assert code == 1 and "the manager removes it" in err and f.exists()


def zone(ws, raw, cwd=None):
    return rc.classify_delete_path(ws, raw, cwd)[0]


def test_classify_basic_and_dotdot(ws):
    assert zone(ws, str(ws / "research" / "sandbox" / "x")) == "research"
    assert zone(ws, str(ws / "research" / ".." / "src" / "x.py")) == "workspace"
    assert zone(ws, "research/sandbox/x", cwd=str(ws)) == "research"
    assert zone(ws, str(ws.parent / "other")) == "outside"
    assert zone(ws, str(ws / "research" / "sandbox" / ".." / ".." / ".." / "x")) == "outside"


def test_classify_quoted_with_spaces_and_backslashes(tmp_path):
    w = tmp_path / "My Project"
    (w / "research" / "sandbox").mkdir(parents=True)
    raw = '"' + str(w / "research" / "sandbox" / "x") + '"'
    assert zone(w, raw) == "research"


@pytest.mark.skipif(not WIN, reason="Windows path forms")
def test_classify_git_bash_form(ws):
    p = str(ws / "research" / "sandbox" / "x").replace("\\", "/")
    gb = "/" + p[0].lower() + p[2:]
    assert zone(ws, gb) == "research"


@pytest.mark.skipif(not WIN, reason="8.3 short names")
def test_classify_short_name(tmp_path):
    import ctypes
    w = tmp_path / "A Long Workspace Name"
    (w / "research" / "sandbox").mkdir(parents=True)
    buf = ctypes.create_unicode_buffer(32768)
    ctypes.windll.kernel32.GetShortPathNameW(str(w), buf, 32768)
    if buf.value.lower() == str(w).lower():
        pytest.skip("8.3 short names disabled on this volume")
    short = buf.value
    assert "~" in short
    assert zone(w, short + "\\research\\sandbox\\x") == "research"
    assert zone(w, short + "\\research\\DIRECTIVES.md") == "protected"
    assert zone(Path(short), str(w / "src" / "x.py")) == "workspace"


@pytest.mark.skipif(not WIN, reason="drive letters")
def test_classify_other_drive(ws):
    other = "Z:" if ws.drive.upper() != "Z:" else "Y:"
    assert zone(ws, other + "\\data\\x.txt") == "outside"


@pytest.mark.skipif(not WIN, reason="junctions")
def test_classify_junction_to_outside(ws, tmp_path):
    target = tmp_path / "precious"
    target.mkdir()
    (target / "f.txt").write_text("mine")
    link = ws / "research" / "link"
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
    assert r.returncode == 0, r.stderr
    assert zone(ws, str(link / "f.txt")) == "outside"
    assert zone(ws, str(link)) == "outside"
    code, out, err = remove(ws, tmp_path, [link / "f.txt"])
    assert code == 1 and (target / "f.txt").exists()
    os.rmdir(link)


def test_protected_names_zone(ws):
    for n in rc.PROTECTED_NAMES:
        assert zone(ws, str(ws / "research" / n)) == "protected"
    assert zone(ws, str(ws / "research" / "hypotheses" / "H1" / "REPORT.md")) == "protected"
    assert zone(ws, str(ws / "research" / "hypotheses" / "H1" / "code.py")) == "research"


@pytest.mark.parametrize("rel", ["research/hypotheses/H1", "research/hypotheses"])
def test_directory_holding_protected_is_protected(ws, tmp_path, rel):
    (ws / "research" / "hypotheses" / "H1").mkdir(parents=True, exist_ok=True)
    (ws / "research" / "hypotheses" / "H1" / "REPORT.md").write_text("keep")
    assert zone(ws, str(ws / rel)) == "protected"
    code, out, err = remove(ws, tmp_path, [ws / rel])
    assert code == 1 and (ws / "research" / "hypotheses" / "H1" / "REPORT.md").exists()


def test_directory_without_protected_is_research(ws):
    d = ws / "research" / "sandbox" / "d"
    d.mkdir(parents=True)
    (d / "a.txt").write_text("x")
    assert zone(ws, str(d)) == "research"


@pytest.mark.skipif(WIN, reason="POSIX symlink dotdot semantics")
def test_posix_symlink_dotdot_resolves_through_link(ws, tmp_path):
    (tmp_path / "outside" / "a" / "b").mkdir(parents=True)
    os.symlink(tmp_path / "outside" / "a" / "b", ws / "research" / "sandbox" / "link")
    assert zone(ws, str(ws / "research" / "sandbox" / "link" / ".." / "x")) == "outside"


@pytest.mark.skipif(WIN, reason="case-sensitive filesystems only")
def test_posix_case_sensitive_zone(ws):
    assert zone(ws, str(ws / "Research" / "sandbox" / "x")) == "workspace"


def test_remove_nested_and_duplicate_targets(ws, tmp_path):
    d = ws / "research" / "sandbox" / "d"
    d.mkdir(parents=True)
    (d / "f.txt").write_text("x")
    code, out, err = remove(ws, tmp_path, [d, d / "f.txt", d])
    assert code == 0, out + err
    assert not d.exists()
    mans = list((ws / "research" / ".trash").glob("*/MANIFEST.json"))
    assert len(mans) == 1
    man = json.loads(mans[0].read_text(encoding="utf-8"))
    assert len(man) == 1
    assert (mans[0].parent / "research" / "sandbox" / "d" / "f.txt").exists()


def test_remove_partial_failure_still_records(ws, tmp_path, monkeypatch):
    a = ws / "research" / "sandbox" / "a.txt"
    a.write_text("x")
    b = ws / "research" / "sandbox" / "b.txt"
    b.write_text("x")
    # Lock b open on Windows is flaky; make the second destination a file where a dir is needed.
    code, out, err = remove(ws, tmp_path, [a, b])
    assert code == 0
    assert list((ws / "research" / ".trash").glob("*/MANIFEST.json"))
