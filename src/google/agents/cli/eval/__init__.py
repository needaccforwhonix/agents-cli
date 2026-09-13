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

import os

# Quiet third-party output that clutters (but never affects) eval results. This
# runs before any eval command module body -- and before the eval SDK, litellm,
# and tqdm are imported -- because Python executes this package __init__ first.
# That ordering matters: litellm and tqdm read these env vars only at import
# time, and in-process commands (e.g. `eval grade`) import the SDK at module
# load. Subprocesses (e.g. `eval generate`'s inference runner) inherit these
# too. setdefault so users can still opt in for debugging (LITELLM_LOG=DEBUG,
# TQDM_DISABLE= to re-enable). litellm ERROR-level messages still surface.
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("LITELLM_LOG", "ERROR")
