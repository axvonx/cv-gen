"""Loop-based Verilator reference; avoids compiling thousands of unrolled clock steps."""

import subprocess
from pathlib import Path

FIELDS = (
    "pc",
    "instruction",
    "a0",
    "sp",
    "result",
    "retired",
    "state",
    "pixel",
    "peek_word",
    "done",
    "fault",
    "screen_address",
    "screen_data",
    "screen_mask",
    "screen_write",
)
WIDTHS = dict(zip(FIELDS, (32, 32, 32, 32, 32, 16, 2, 8, 32, 1, 1, 8, 32, 4, 1), strict=True))
INPUTS = {
    "clk": 1,
    "rst": 1,
    "run": 1,
    "boot_ram": 1,
    "load_enable": 1,
    "inspect": 1,
    "load_address": 16,
    "peek_address": 16,
    "load_data": 32,
}


def reference(spec, directory, loads, limit):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["module bench;"]
    for name, width in {**INPUTS, **WIDTHS}.items():
        lines += [f"logic [{width - 1}:0] {name};"]
    lines += [
        "rv32_graphics dut(" + ",".join(f".{name}({name})" for name in (*INPUTS, *FIELDS)) + ");",
        "initial begin",
    ]
    lines += [f"{name}=0;" for name in INPUTS]
    lines += ["rst=1;#1;rst=0;#1;"]
    for item in loads:
        lines += [
            f"load_address=16'd{item['address']};load_data=32'd{item['data']};#1;",
            "load_enable=1;#1;load_enable=0;#1;",
        ]
    lines += [
        f"boot_ram={int(bool(loads))};rst=1;#1;rst=0;#1;run=1;#1;",
        f"for(integer cycle=1;cycle<={limit};cycle=cycle+1)begin",
        "clk=1;#1;",
        '$display("@CPU %0d '
        + " ".join("%0d" for _ in FIELDS)
        + '",cycle,'
        + ",".join(FIELDS)
        + ");",
        "clk=0;#1;if(done || fault)break;end",
        "run=0;inspect=1;#1;",
        "for(integer pixel_index=0;pixel_index<256;pixel_index=pixel_index+1)begin",
        "peek_address=16'hf000+16'(pixel_index);#1;"
        '$display("@PIX %0d %0d",pixel_index,pixel);end',
        'peek_address=16\'he100;#1;$display("@FAR %0d",peek_word);',
        'peek_address=16\'hfffc;#1;$display("@LAST %0d",peek_word);',
        "$finish;end endmodule",
    ]
    tb = directory / "bench.sv"
    tb.write_text("\n".join(lines) + "\n")
    result = subprocess.run(
        [
            "verilator",
            "--binary",
            "--timing",
            "-Wno-fatal",
            "--top-module",
            "bench",
            "--Mdir",
            str(directory / "obj"),
            *[str(p) for p in spec.sources],
            str(tb),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-6000:])
    output = subprocess.check_output([str(directory / "obj/Vbench")], text=True)
    rows = []
    pixels = []
    extra = {}
    for line in output.splitlines():
        if line.startswith("@CPU "):
            values = list(map(int, line.split()[1:]))
            rows.append(dict(zip(("cycle", *FIELDS), values, strict=True)))
        elif line.startswith("@PIX "):
            pixels.append(int(line.split()[2]))
        elif line.startswith("@FAR "):
            extra["far_word"] = int(line.split()[1])
        elif line.startswith("@LAST "):
            extra["last_word"] = int(line.split()[1])
    if not rows or rows[-1]["fault"] or not rows[-1]["done"]:
        raise RuntimeError(
            f"Verilator did not complete within {limit} cycles: {rows[-1] if rows else None}"
        )
    return {"rows": rows, "pixels": pixels, **extra}
