"""Tests for the cross-platform WebAssembly build command."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import build  # noqa: E402


def test_wasm_command_uses_path_on_posix():
    line = "em++ -std=gnu++17 -O2"
    assert build.wasm_shell_command(line, r"C:\emsdk_env.bat", platform="posix") == line


if __name__ == "__main__":
    test_wasm_command_uses_path_on_posix()
    print("ok  test_wasm_command_uses_path_on_posix")
