from cv_gen.generator import GenerationOptions, generate_csv
from cv_gen.tests_catalog import find_test


def test_alu16_ops_directly():
    test = find_test("alu16")
    assert test is not None

    a, b = 0b1010_1010_1010_1010, 0b0110_0110_0110_0110

    assert test.generate({"IN A": a, "IN B": b, "IN OP": 0}) == {"OUT": (a + b) & 0xFFFF}
    assert test.generate({"IN A": a, "IN B": b, "IN OP": 1}) == {"OUT": (~a) & 0xFFFF}
    assert test.generate({"IN A": a, "IN B": b, "IN OP": 2}) == {"OUT": a & b}
    assert test.generate({"IN A": a, "IN B": b, "IN OP": 3}) == {"OUT": a}


def test_alu16_add_wraps_at_16_bits():
    test = find_test("alu16")
    assert test is not None

    result = test.generate({"IN A": 0xFFFF, "IN B": 0x0002, "IN OP": 0})
    assert result == {"OUT": 0x0001}


def test_alu16_csv_header_and_shape():
    test = find_test("alu16")
    assert test is not None

    csv, summary = generate_csv(test, GenerationOptions(intensity=100, max_cases=8_000, seed=42))
    lines = csv.splitlines()

    assert lines[0] == "comb,16-bit ALU (2-bit Selector) Validation"
    assert lines[1] == "Inputs BandWidth: 16,16,2"
    assert lines[2] == "Outputs BandWidth: 16"
    assert lines[3] == "Inputs Name: IN A,IN B,IN OP"
    assert lines[4] == "Outputs Name: OUT"
    assert summary.generated_cases == 8_000
