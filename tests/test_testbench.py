import pytest

from cv_gen.generator import GenerationOptions, generate_csv, generate_testbench
from cv_gen.testbench import Group, Series, TestData, validate
from cv_gen.tests_catalog import find_test


def test_csv_round_trip_is_exact():
    test = find_test("cla4")
    csv, _ = generate_csv(test, GenerationOptions(intensity=10, seed=3))
    assert TestData.from_csv(csv).to_csv() == csv


def test_json_round_trip_and_n():
    data, _ = generate_testbench(find_test("cla4"), GenerationOptions(intensity=5))
    encoded = data.to_json()
    assert encoded["groups"][0]["n"] == data.case_count
    assert TestData.from_json(encoded) == data
    wrapped = data.to_testbench_data()
    assert wrapped["currentGroup"] == 0 and wrapped["currentCase"] == 0


def _data(values=("0", "1"), width=1, label="A", out_label="Y", n_out=None):
    outputs = (Series(out_label, 1, tuple(n_out or ("0", "1"))),)
    return TestData("comb", "t", (Group("G", (Series(label, width, values),), outputs),))


@pytest.mark.parametrize(
    "data, fragment",
    [
        (_data(label="Q"), "no input labelled 'Q'"),
        (_data(values=("00", "01"), width=2), "2 bits in the test but 1 bits"),
        (_data(values=("0", "2")), "expected 1 binary digits"),
        (_data(n_out=("0",)), "has 1 values, expected 2"),
        (_data(label="A:B"), "contains , :"),
    ],
)
def test_validate_reports_problems(data, fragment):
    problems = validate(data, {"A": 1}, {"Y": 1})
    assert any(fragment in problem for problem in problems), problems


def test_validate_accepts_matching_data():
    assert validate(_data(), {"A": 1}, {"Y": 1}) == []


def test_seq_requires_rst():
    data = TestData("seq", "t", _data().groups)
    assert any("RST" in p for p in validate(data, {"A": 1}, {"Y": 1}))


def test_groups_must_share_ports():
    first = _data().groups[0]
    other = Group("H", (Series("A", 1, ("0",)),), (Series("Z", 1, ("0",)),))
    problems = validate(TestData("comb", "t", (first, other)), {"A": 1}, {"Y": 1, "Z": 1})
    assert any("differ from the first group" in p for p in problems)
