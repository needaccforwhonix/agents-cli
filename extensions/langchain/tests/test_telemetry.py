# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import importlib.util
import os
from pathlib import Path

import pytest

_EXTENSION_DIR = next(
    p / "extensions" / "langchain" / "template"
    for p in Path(__file__).resolve().parents
    if (p / "extensions" / "langchain" / "template").is_dir()
)

# Tests live inside the extension, so paths are relative to the extension root.
_TELEMETRY_PATH = _EXTENSION_DIR / "app/app_utils/telemetry.py"

# GenAI env-vars the capture setup manages.
_GENAI_VARS = (
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
    "OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT",
    "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK",
    "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH",
    "OTEL_SEMCONV_STABILITY_OPT_IN",
    "GENAI_TELEMETRY_PATH",
    "LOGS_BUCKET_NAME",
)


def _load():
    spec = importlib.util.spec_from_file_location("lg_telemetry", str(_TELEMETRY_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _clear(monkeypatch):
    for var in _GENAI_VARS:
        monkeypatch.delenv(var, raising=False)


class TestConfigureGenaiCapture:
    def test_disabled_without_bucket(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "NO_CONTENT"
        )
        _load()._configure_genai_capture()
        assert "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH" not in os.environ

    def test_disabled_when_capture_off(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("LOGS_BUCKET_NAME", "my-bucket")
        # capture defaults to "false" — logging stays off even with a bucket.
        _load()._configure_genai_capture()
        assert "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH" not in os.environ

    def test_enabled_sets_upload_contract(self, monkeypatch):
        _clear(monkeypatch)
        monkeypatch.setenv("LOGS_BUCKET_NAME", "my-bucket")
        monkeypatch.setenv(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "NO_CONTENT"
        )
        _load()._configure_genai_capture()
        assert (
            os.environ["OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH"]
            == "gs://my-bucket/completions"
        )
        assert os.environ["OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK"] == "upload"
        assert os.environ["OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT"] == "jsonl"


class TestCloudExportSwitch:
    """ADK reads this var to decide whether to export; so must this template."""

    @pytest.mark.parametrize(
        "value,enabled",
        [
            (None, True),
            ("true", True),
            ("TRUE", True),
            ("1", True),
            ("false", False),
            ("False", False),
            ("0", False),
            ("", False),
        ],
    )
    def test_switch(self, monkeypatch, value, enabled):
        if value is None:
            monkeypatch.delenv(
                "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", raising=False
            )
        else:
            monkeypatch.setenv("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", value)
        assert _load()._cloud_export_enabled() is enabled

    def test_off_skips_the_exporters(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "false")
        mod = _load()
        called = []
        mod._setup_cloud_exporters = lambda: called.append(1)
        mod._install_instrumentation = lambda: None
        mod.setup_telemetry()
        assert not called
