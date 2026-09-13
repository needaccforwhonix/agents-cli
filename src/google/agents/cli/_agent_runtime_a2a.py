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

"""Shared construction of the Agent Runtime A2A card URL.

The container Agent Runtime serves its A2A card through the Agent Engine
HTTP passthrough at ``/api/a2a/<agent_directory>``. Both ``deploy`` (when
advertising the card) and ``publish``/``run`` (when fetching it) must build
the exact same URL, so the format lives here in one place.
"""

from __future__ import annotations

from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH


def build_agent_runtime_a2a_base_url(
    location: str, runtime_resource: str, agent_directory: str
) -> str:
    """Base URL the A2A client targets. ``runtime_resource`` is the full
    ``projects/<num>/locations/<loc>/reasoningEngines/<id>`` resource name."""
    return (
        f"https://{location}-aiplatform.googleapis.com/reasoningEngines/v1/"
        f"{runtime_resource}/api/a2a/{agent_directory}"
    )


def build_agent_runtime_a2a_card_url(
    location: str, runtime_resource: str, agent_directory: str
) -> str:
    """Well-known agent-card URL — what ``deploy`` advertises and ``publish`` registers."""
    base = build_agent_runtime_a2a_base_url(location, runtime_resource, agent_directory)
    return f"{base}{AGENT_CARD_WELL_KNOWN_PATH}"
