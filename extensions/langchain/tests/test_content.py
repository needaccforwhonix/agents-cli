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

"""Guard the LangChain content->text normalizer used by the A2A executor.

Regression: LangChain 1.x streams message content as a list of content blocks,
which broke `Part(text=...)` (needs a string) in the A2A serving path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_EXTENSION_DIR = next(
    p / "extensions" / "langchain" / "template"
    for p in Path(__file__).resolve().parents
    if (p / "extensions" / "langchain" / "template").is_dir()
)
_CONTENT_PATH = _EXTENSION_DIR / "app/app_utils/content.py"


def _load():
    spec = importlib.util.spec_from_file_location("lg_content", str(_CONTENT_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestContentToText:
    """Traces carry a string; LangChain 1.x hands back a list of blocks."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("already text", "already text"),
            ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "ab"),
            ([{"type": "image", "url": "x"}, "tail"], "tail"),
            ([], ""),
            (None, ""),
        ],
    )
    def test_flattens_to_text(self, value, expected):
        assert _load().content_to_text(value) == expected
