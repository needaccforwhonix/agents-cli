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

"""agents-cli infra show — read the provisioned infrastructure's outputs."""

from __future__ import annotations

import logging
from typing import Any

import click

from google.agents.cli._output import emit
from google.agents.cli._project import chdir_project_root
from google.agents.cli._tools import require_tool
from google.agents.cli.infra._terraform import (
    read_terraform_outputs,
    require_single_project_tf_dir,
)

REDACTED = "<sensitive>"


def _flatten(
    outputs: dict[str, dict[str, Any]], *, include_sensitive: bool
) -> tuple[dict[str, Any], list[str]]:
    """Reduce Terraform's output records to name -> value, redacting secrets.

    Returns the values and the names that were redacted.
    """
    values: dict[str, Any] = {}
    redacted: list[str] = []
    for name, record in sorted(outputs.items()):
        sensitive = bool(record.get("sensitive"))
        if sensitive and not include_sensitive:
            values[name] = REDACTED
            redacted.append(name)
        else:
            values[name] = record.get("value")
    return values, redacted


@click.command("show")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
@click.option(
    "--include-sensitive",
    is_flag=True,
    default=False,
    help="Include values Terraform marked sensitive, in cleartext.",
)
def cmd_infra_show(as_json: bool, include_sensitive: bool) -> None:
    """Show the outputs of the single-project Terraform root.

    \b
    Reads the values `agents-cli infra single-project --apply` provisioned —
    service account emails, bucket names, and the deployed resource names for
    the project's deployment target — without the caller having to know where
    the scaffold puts the Terraform root.

    \b
    Values Terraform marked sensitive are redacted; pass --include-sensitive to
    print them.
    """
    chdir_project_root()
    require_tool("terraform")

    tf_dir = require_single_project_tf_dir()
    outputs = read_terraform_outputs(tf_dir)
    values, redacted = _flatten(outputs, include_sensitive=include_sensitive)

    if as_json:
        emit({"tf_dir": str(tf_dir), "outputs": values})
        return

    if not values:
        click.echo(f"No Terraform outputs in '{tf_dir}'.")
        click.echo("  Provision it first:")
        click.echo("    agents-cli infra single-project --apply")
        return

    width = max(len(name) for name in values)
    for name, value in values.items():
        click.echo(f"{name.ljust(width)}  {value}")
    if redacted:
        logging.warning(
            "Redacted %d sensitive output(s): %s. Pass --include-sensitive to show them.",
            len(redacted),
            ", ".join(redacted),
        )
