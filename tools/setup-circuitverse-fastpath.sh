#!/bin/sh
# Isolated SDK: deliberately does not edit shell startup files or the native engine cache.
set -eu
task_sdk="${XDG_CACHE_HOME:-$HOME/.cache}/cv-gen/emsdk-6.0.10"
if [ ! -f "$task_sdk/emsdk" ]; then
    git clone --depth 1 --branch 6.0.10 https://github.com/emscripten-core/emsdk.git "$task_sdk"
fi
"$task_sdk/emsdk" install 6.0.10
"$task_sdk/emsdk" activate 6.0.10
printf 'SDK ready at %s\n' "$task_sdk"
verilator --version
printf 'The package builder requires Verilator 5.052, Yosys, clang++, Node and uv.\n'
