"""CircuitVerse testbench data: the structure stored at ``scope.testbenchData``.

One in-memory form (``TestData``) with two serializations: CircuitVerse JSON, which is
what the simulator stores and runs, and the simulator's CSV import/export dialect.
"""

from dataclasses import dataclass
from typing import Any

UNSAFE_LABEL_CHARACTERS = ",\r\n:"


@dataclass(frozen=True, slots=True)
class Series:
    label: str
    bit_width: int
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Group:
    label: str
    inputs: tuple[Series, ...]
    outputs: tuple[Series, ...]

    @property
    def n(self) -> int:
        return len(self.inputs[0].values) if self.inputs else 0


@dataclass(frozen=True, slots=True)
class TestData:
    __test__ = False  # not a pytest test class

    type: str
    title: str
    groups: tuple[Group, ...]

    @property
    def case_count(self) -> int:
        return sum(group.n for group in self.groups)

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "title": self.title,
            "groups": [
                {
                    "label": group.label,
                    "inputs": [_series_json(series) for series in group.inputs],
                    "outputs": [_series_json(series) for series in group.outputs],
                    "n": group.n,
                }
                for group in self.groups
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "TestData":
        return cls(
            type=data["type"],
            title=data.get("title", ""),
            groups=tuple(
                Group(
                    label=group.get("label", ""),
                    inputs=tuple(_series_from_json(series) for series in group["inputs"]),
                    outputs=tuple(_series_from_json(series) for series in group["outputs"]),
                )
                for group in data["groups"]
            ),
        )

    def to_testbench_data(self) -> dict[str, Any]:
        """The object stored at ``scope.testbenchData``."""
        return {"currentGroup": 0, "currentCase": 0, "testData": self.to_json()}

    def to_csv(self) -> str:
        """The simulator's CSV dialect (plain string splitting, not RFC 4180)."""
        first = self.groups[0]
        lines = [
            f"{self.type},{self.title}",
            f"Inputs BandWidth: {','.join(str(s.bit_width) for s in first.inputs)}",
            f"Outputs BandWidth: {','.join(str(s.bit_width) for s in first.outputs)}",
            f"Inputs Name: {','.join(s.label for s in first.inputs)}",
            f"Outputs Name: {','.join(s.label for s in first.outputs)}",
        ]
        for group in self.groups:
            lines.append(f"G-{group.label}:")
            lines.extend(f"I-{s.label}:{','.join(s.values)}" for s in group.inputs)
            lines.extend(f"O-{s.label}:{','.join(s.values)}" for s in group.outputs)
        return "\n".join(lines) + "\n"

    @classmethod
    def from_csv(cls, text: str) -> "TestData":
        lines = text.strip("\n").split("\n")
        kind, title = lines[0].split(",", 1)
        input_widths = _csv_header(lines[1], "Inputs BandWidth")
        output_widths = _csv_header(lines[2], "Outputs BandWidth")
        groups: list[Group] = []
        label = ""
        inputs: list[Series] = []
        outputs: list[Series] = []

        def close_group() -> None:
            if inputs or outputs:
                groups.append(Group(label, tuple(inputs), tuple(outputs)))

        for line in lines[5:]:
            tag, rest = line.split("-", 1)
            if tag == "G":
                close_group()
                label, inputs, outputs = rest.removesuffix(":"), [], []
                continue
            series_label, values = rest.rsplit(":", 1)
            target, widths = (inputs, input_widths) if tag == "I" else (outputs, output_widths)
            target.append(Series(series_label, widths[len(target)], tuple(values.split(","))))
        close_group()
        return cls(kind, title, tuple(groups))


def _series_json(series: Series) -> dict[str, Any]:
    return {"label": series.label, "bitWidth": series.bit_width, "values": list(series.values)}


def _series_from_json(data: dict[str, Any]) -> Series:
    return Series(data["label"], int(data["bitWidth"]), tuple(data["values"]))


def _csv_header(line: str, name: str) -> list[int]:
    prefix = f"{name}: "
    if not line.startswith(prefix):
        raise ValueError(f"expected CSV header {name!r}, got {line!r}")
    return [int(width) for width in line[len(prefix) :].split(",")]


def format_value(value: int, width: int) -> str:
    return f"{value & ((1 << width) - 1):0{width}b}"


def validate(data: TestData, inputs: dict[str, int], outputs: dict[str, int]) -> list[str]:
    """Check ``data`` against a scope's port map ``{label: bit width}``.

    Mirrors the simulator's own validation and adds the checks it skips (value format,
    per-group length consistency), because the simulator silently misbehaves on those.
    """
    problems: list[str] = []
    if data.type not in ("comb", "seq"):
        problems.append(f"unknown testbench type {data.type!r}")
    if not data.groups:
        problems.append("testbench has no groups")
    if data.type == "seq" and inputs.get("RST") != 1:
        problems.append("sequential testbenches need a 1-bit input labelled RST")

    for group in data.groups:
        where = f"group {group.label!r}"
        if not group.inputs or not group.outputs:
            problems.append(f"{where}: needs at least one input and one output")
            continue
        # The simulator binds ports from the first group only.
        first = data.groups[0]
        if [s.label for s in group.inputs] != [s.label for s in first.inputs] or [
            s.label for s in group.outputs
        ] != [s.label for s in first.outputs]:
            problems.append(f"{where}: ports differ from the first group's")
        for kind, series_list, ports in (
            ("input", group.inputs, inputs),
            ("output", group.outputs, outputs),
        ):
            labels = [series.label.strip() for series in series_list]
            if len(labels) != len(set(labels)):
                problems.append(f"{where}: duplicate {kind} labels")
            for series in series_list:
                label = series.label.strip()
                if any(character in label for character in UNSAFE_LABEL_CHARACTERS):
                    problems.append(f"{where}: {kind} {label!r} contains , : or a newline")
                if label not in ports:
                    problems.append(f"{where}: circuit has no {kind} labelled {label!r}")
                elif ports[label] != series.bit_width:
                    problems.append(
                        f"{where}: {kind} {label!r} is {series.bit_width} bits in the test "
                        f"but {ports[label]} bits in the circuit"
                    )
                if len(series.values) != group.n:
                    problems.append(f"{where}: {kind} {label!r} has {len(series.values)} values, "
                                    f"expected {group.n}")
                bad = next(
                    (v for v in series.values
                     if len(v) != series.bit_width or v.strip("01")),
                    None,
                )
                if bad is not None:
                    problems.append(
                        f"{where}: {kind} {label!r} has value {bad!r}, "
                        f"expected {series.bit_width} binary digits"
                    )
    return problems
