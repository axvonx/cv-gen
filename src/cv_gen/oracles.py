"""Oracles: the expected behaviour of a circuit, written in Python.

A project keeps its oracles in its own module (named by ``generate.oracles`` in
``cvgen-tests.toml``) and marks them with the decorators below::

    from cv_gen.oracles import comb, trace, TraceOracle

    @comb("and16")
    def and16(v):
        return v["IN A"] & v["IN B"]          # a bare int means "the only output"

    @trace("register16")
    class Register16(TraceOracle): ...
"""

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .model import Values
from .trace import TraceOracle

CombOracle = Callable[[Values], Values | int]

_MARK = "__cv_gen_oracle__"


def comb(name: str) -> Callable[[CombOracle], CombOracle]:
    def mark(function: CombOracle) -> CombOracle:
        setattr(function, _MARK, ("comb", name))
        return function

    return mark


def trace(name: str) -> Callable[[type[TraceOracle]], type[TraceOracle]]:
    def mark(cls: type[TraceOracle]) -> type[TraceOracle]:
        if not (isinstance(cls, type) and issubclass(cls, TraceOracle)):
            raise TypeError(f"@trace({name!r}) must decorate a TraceOracle subclass")
        setattr(cls, _MARK, ("trace", name))
        return cls

    return mark


@dataclass
class Registry:
    comb: dict[str, CombOracle] = field(default_factory=dict)
    trace: dict[str, type[TraceOracle]] = field(default_factory=dict)

    def kind_of(self, name: str) -> str | None:
        if name in self.comb:
            return "comb"
        if name in self.trace:
            return "trace"
        return None


def load_oracles(path: str | Path) -> Registry:
    path = Path(path).resolve()
    module_name = f"_cv_gen_oracles_{abs(hash(path))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import oracles from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    registry = Registry()
    for value in vars(module).values():
        mark = getattr(value, _MARK, None)
        if mark is None:
            continue
        kind, name = mark
        table = registry.comb if kind == "comb" else registry.trace
        if name in registry.comb or name in registry.trace:
            raise ValueError(f"oracle {name!r} is defined twice in {path}")
        table[name] = value
    return registry
