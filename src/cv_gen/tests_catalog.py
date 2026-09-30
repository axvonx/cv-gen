from .model import Signal, TestCase, Values


def _cla_add(values: Values, width: int) -> Values:
    full = values["IN A"] + values["IN B"] + values["IN Carry"]
    return {
        "OUT": full & ((1 << width) - 1),
        "OUT Carry": (full >> width) & 1,
    }


def _cla4(values: Values) -> Values:
    return _cla_add(values, 4)


def _cla16(values: Values) -> Values:
    return _cla_add(values, 16)


def _alu16(values: Values) -> Values:
    a = values["IN A"]
    b = values["IN B"]
    op = values["IN OP"]
    if op == 0:
        result = a + b & 0xFFFF
    elif op == 1:
        result = ~a & 0xFFFF
    elif op == 2:
        result = a & b
    else:
        result = a
    return {"OUT": result}


TESTS = (
    TestCase(
        name="4-bit CLA Adder Validation",
        alias="cla4",
        inputs=(Signal("IN A", 4), Signal("IN B", 4), Signal("IN Carry", 1)),
        outputs=(Signal("OUT", 4), Signal("OUT Carry", 1)),
        generate=_cla4,
    ),
    TestCase(
        name="16-bit CLA Adder Validation",
        alias="cla16",
        inputs=(Signal("IN A", 16), Signal("IN B", 16), Signal("IN Carry", 1)),
        outputs=(Signal("OUT", 16), Signal("OUT Carry", 1)),
        generate=_cla16,
        max_cases=65_536,
    ),
    TestCase(
        name="16-bit ALU (2-bit Selector) Validation",
        alias="alu16",
        inputs=(Signal("IN A", 16), Signal("IN B", 16), Signal("IN OP", 2)),
        outputs=(Signal("OUT", 16),),
        generate=_alu16,
    ),
)


def find_test(name: str) -> TestCase | None:
    return next((test for test in TESTS if name in (test.name, test.alias)), None)
