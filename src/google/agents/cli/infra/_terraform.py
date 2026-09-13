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

"""The scaffolded single-project Terraform root, and how to read it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from google.agents.cli._runner import run_resolved

# Where the scaffold puts the single-project Terraform root, relative to the
# project root. Defined once so that every command agrees, and so that callers
# outside the CLI never have to hardcode it.
SINGLE_PROJECT_TF_DIR = Path("deployment/terraform/single-project")


def require_single_project_tf_dir() -> Path:
    """Return the single-project Terraform root, or fail with guidance."""
    if not SINGLE_PROJECT_TF_DIR.is_dir():
        raise click.ClickException(
            f"Terraform directory '{SINGLE_PROJECT_TF_DIR}' not found.\n"
            "  Ensure your project was scaffolded with a deployment target that includes Terraform.\n"
            "  Run 'agents-cli scaffold enhance' to add deployment infrastructure."
        )
    return SINGLE_PROJECT_TF_DIR


def read_terraform_outputs(tf_dir: Path) -> dict[str, dict[str, Any]]:
    """Read a Terraform root's outputs, in Terraform's own `output -json` shape.

    Each entry is ``{"sensitive": bool, "type": ..., "value": ...}``. An
    unprovisioned root has no outputs and yields an empty dict.
    """
    result = run_resolved(
        ["terraform", "output", "-json"],
        cwd=tf_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise click.ClickException(
            f"Could not read Terraform outputs from '{tf_dir}'.\n"
            f"  terraform: {stderr or 'exited with status ' + str(result.returncode)}\n"
            "  If the root has never been initialized, run "
            "'agents-cli infra single-project --apply' first."
        )

    try:
        outputs = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise click.ClickException(
            f"Terraform returned output that is not valid JSON: {exc}"
        ) from exc

    if not isinstance(outputs, dict):
        raise click.ClickException(
            "Terraform returned outputs in an unexpected shape "
            f"({type(outputs).__name__}); expected a JSON object."
        )
    return outputs
