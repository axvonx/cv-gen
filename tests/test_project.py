import pytest

from cv_gen import project
from cv_gen.testbench import Group, Series, TestData


def and_test(width=1):
    values = tuple(format(i, f"0{width}b") for i in range(2))
    return TestData("comb", "and", (Group("G", (
        Series("A", width, values), Series("B", width, values)), (Series("Y", width, values),)),))


def test_scopes_reads_ports_and_dependencies(document):
    infos = {info.name: info for info in project.scopes(document)}
    assert [(p.label, p.width) for p in infos["AND4"].inputs] == [("A", 4), ("B", 4)]
    assert infos["AND4"].dependencies == {"1"}
    assert project.dependency_names(document) == {"AND": set(), "AND4": {"AND"}, "Reg": {"AND4"}}


def test_inject_changes_only_the_target_testbench(document):
    result = project.inject(document, {"AND": and_test()})
    assert "testbenchData" not in document["scopes"][0]  # input untouched
    assert result["scopes"][0]["testbenchData"]["testData"]["title"] == "and"
    assert project.non_testbench_view(result) == project.non_testbench_view(document)
    assert "testbenchData" not in result["scopes"][1]


def test_inject_validates_before_modifying(document):
    with pytest.raises(project.ProjectError, match="1 bits in the test but 4 bits"):
        project.inject(document, {"AND4": and_test(width=1)})


def test_find_scope_by_name_or_id_and_ambiguity(document):
    assert project.find_scope(document, "3").name == "Reg"
    with pytest.raises(project.ProjectError, match="no circuit named"):
        project.find_scope(document, "missing")
    document["scopes"].append(dict(document["scopes"][0], id=9))
    with pytest.raises(project.ProjectError, match="ambiguous"):
        project.find_scope(document, "AND")


def test_canonical_hash_ignores_key_order(document):
    reordered = {key: document[key] for key in reversed(list(document))}
    assert project.canonical_hash(reordered) == project.canonical_hash(document)
