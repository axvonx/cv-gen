from cv_gen.report import build_report, render_text

DEPS = {"AND": set(), "AND3": {"AND"}, "ADD": {"AND3"}, "REG": set(), "OR": set()}


def raw(statuses):
    return {"project": "p", "loadMs": 1, "scopes": [
        {"scope": name, "status": status, "passed": 0 if status == "fail" else 4, "total": 4,
         "failures": [{"case": 1, "inputs": {"A": "1"},
                       "diffs": [{"output": "Y", "expected": "1", "got": "0"}]}]
         if status == "fail" else []}
        for name, status in statuses.items()
    ]}


def test_root_cause_is_failing_scope_without_failing_dependencies():
    report = build_report(raw({"AND": "fail", "AND3": "fail", "ADD": "fail", "REG": "fail",
                               "OR": "pass"}), DEPS)
    assert {r.scope for r in report.root_causes} == {"AND", "REG"}
    assert report.downstream_of("AND") == ["ADD", "AND3"]
    assert not report.ok


def test_render_shows_every_failure_but_hides_passes():
    report = build_report(raw({"AND": "fail", "AND3": "fail", "OR": "pass"}), DEPS)
    text = render_text(report, unchecked={"AND3": 2})
    assert "FAIL AND " in text and "FAIL AND3" in text and " OR " not in text
    assert "uses failing subcircuit(s): AND" in text
    assert "(2 unchecked)" in text
    assert "1 passed, 2 failed (1 likely root cause)" in text


def test_engine_error_is_a_failure():
    report = build_report(raw({"OR": "engine-error"}), DEPS)
    assert not report.ok
    assert "not trustworthy" in render_text(report)
