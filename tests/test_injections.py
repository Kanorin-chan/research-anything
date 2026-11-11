import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ra_common as rc  # noqa: E402

ANSWER = {"worker-handover", "review-meeting", "before-delete", "before-other-agent",
          "before-graduation", "expert-handover"}
REMIND = {"session-start", "worker-dispatch", "before-build"}


def test_every_moment_template_loads():
    assert len(ANSWER | REMIND) == 9
    for moment in ANSWER | REMIND:
        inj = rc.load_injection(moment)
        assert inj["moment"] == moment
        assert inj["level"] == ("answer" if moment in ANSWER else "remind")
        assert set(inj["placeholders"]) == set(re.findall(r"\{(\w+)\}", inj["body"])), moment
        if moment in ANSWER:
            assert inj["questions"], moment
    assert "fake any data" in rc.load_injection("worker-handover")["body"]


def test_render_fills_and_marks_missing():
    out = rc.render_injection("before-delete", targets="research/sandbox/x")
    assert "research/sandbox/x" in out
    assert "{unknown: workspace}" in out


def test_check_answers_rejects_bare_yes():
    probs = rc.check_answers("1. yes\n2. ok\n3. ...\n4. ...", "before-delete")
    assert any("question 1" in p for p in probs)
    assert any("question 2" in p for p in probs)


def test_check_answers_rejects_missing_number():
    text = "1. All paths are under research/sandbox, I listed them.\n2. Nothing imports it, grep found no hits.\n4. Moved to .trash so restorable."
    probs = rc.check_answers(text, "before-delete")
    assert len(probs) == 1 and "question 3" in probs[0]


def test_check_answers_accepts_reasons():
    text = ("1. Yes, all under research/sandbox/tmp.\n2. No; grep -rn found no references.\n"
            "3. Not user data, I created it this session.\n4. Recoverable from research/.trash.")
    assert rc.check_answers(text, "before-delete") == []


def test_numeric_line_inside_answer_is_not_a_new_answer():
    text = ("1. All paths are under research/sandbox.\n"
            "2. Nothing imports it; checked the score:\n0.31 is below target\n2.5 seconds per run\n"
            "3. Not user data, created this session.\n4. Recoverable from research/.trash.")
    assert rc.check_answers(text, "before-delete") == []


def test_load_injection_refuses_traversal():
    import pytest
    with pytest.raises(ValueError):
        rc.load_injection("../x")


def test_templates_do_not_say_one_file_per_question():
    for moment in ANSWER:
        assert "per question" not in rc.load_injection(moment)["body"]
