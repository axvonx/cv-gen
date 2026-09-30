from collections.abc import Callable
from dataclasses import dataclass

Values = dict[str, int]
TestFunction = Callable[[Values], Values]


@dataclass(frozen=True, slots=True)
class Signal:
    name: str
    width: int


@dataclass(frozen=True, slots=True)
class TestCase:
    name: str
    alias: str | None
    inputs: tuple[Signal, ...]
    outputs: tuple[Signal, ...]
    generate: TestFunction
    max_cases: int = 0

    @property
    def input_bits(self) -> int:
        return sum(signal.width for signal in self.inputs)
