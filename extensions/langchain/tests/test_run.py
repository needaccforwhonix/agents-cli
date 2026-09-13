# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Argv handling for the `run` override, which replaces the built-in's parser."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_EXTENSION_DIR = next(
    p / "extensions" / "langchain" / "template"
    for p in Path(__file__).resolve().parents
    if (p / "extensions" / "langchain" / "template").is_dir()
)
_SCRIPT_PATH = _EXTENSION_DIR / "scripts/run.py"

# The script imports a sibling module the way python does when run as a file.
sys.path.insert(0, str(_EXTENSION_DIR / "scripts"))


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("lc_run", str(_SCRIPT_PATH))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seen(monkeypatch) -> list[str]:
    """Record the prompt the stub graph is invoked with."""
    prompts: list[str] = []

    def invoke(state):
        prompts.append(state["messages"][-1]["content"])
        return {"messages": [types.SimpleNamespace(content="ok")]}

    app = types.ModuleType("app")
    agent = types.ModuleType("app.agent")
    agent.root_agent = types.SimpleNamespace(invoke=invoke)
    monkeypatch.setitem(sys.modules, "app", app)
    monkeypatch.setitem(sys.modules, "app.agent", agent)
    return prompts


def _run(mod, argv: list[str], monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["run.py", *argv])
    return mod.main()


class TestArgv:
    def test_sends_the_single_message(self, mod, seen, monkeypatch):
        assert _run(mod, ["what is the weather"], monkeypatch) == 0
        assert seen == ["what is the weather"]

    def test_extra_words_are_rejected_not_joined(self, mod, seen, monkeypatch):
        """Matches the built-in: the message is one argument, quoted."""
        with pytest.raises(SystemExit) as exit_info:
            _run(mod, ["hello", "there"], monkeypatch)
        assert exit_info.value.code == 2
        assert seen == []

    def test_no_message_is_a_usage_error(self, mod, monkeypatch):
        with pytest.raises(SystemExit) as exit_info:
            _run(mod, [], monkeypatch)
        assert exit_info.value.code == 2

    @pytest.mark.parametrize(
        "argv", [["--url", "https://agent.example", "hi"], ["--mode", "a2a", "hi"]]
    )
    def test_remote_flags_are_refused_with_a_way_out(
        self, mod, argv, monkeypatch, capsys
    ):
        assert _run(mod, argv, monkeypatch) == 2
        assert "AGENTS_CLI_DISABLE_OVERRIDES=1" in capsys.readouterr().err
