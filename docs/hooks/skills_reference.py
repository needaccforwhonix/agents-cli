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

"""MkDocs hook to auto-generate the skills reference page from SKILL.md frontmatter."""

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "skills"
OUTPUT_FILE = Path(__file__).resolve().parent.parent / "src" / "reference" / "skills.md"

HEADER = """# Skills Reference

Skills are context files installed to coding agents (Antigravity CLI, Claude Code, GitHub Copilot) via `agents-cli setup`. They provide domain-specific guidance for working with generated agent projects.

```bash
agents-cli setup      # Install all skills
agents-cli update     # Reinstall / update skills
```

---

"""


def _parse_frontmatter(path: Path) -> dict:
    text = path.read_text()
    match = re.match(r"^---\n(.+?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm = {}
    current_key = None
    for line in match.group(1).splitlines():
        kv = re.match(r"^(\w[\w-]*):\s*(.*)", line)
        if kv:
            current_key = kv.group(1)
            fm[current_key] = kv.group(2).strip()
        elif current_key and line.startswith("  "):
            fm[current_key] = (fm[current_key] + " " + line.strip()).strip()
    return fm


def _clean_description(desc: str) -> str:
    """Extract the user-facing description, drop routing instructions."""
    # Remove "Do NOT use for..." suffix
    desc = re.split(r"\s*Do NOT use for", desc)[0].strip()
    # Remove leading preamble up to the actual description.
    # Descriptions follow the pattern: routing text. Actual description.
    # Split on first sentence that starts with a capital and isn't the preamble.
    match = re.search(r"(?:Covers |Always active|It provides |Provides )", desc)
    if match:
        desc = desc[match.start() :]
    # Remove trailing ">" from YAML folded strings
    desc = desc.strip().rstrip(">").strip()
    # Capitalize first letter
    if desc:
        desc = desc[0].upper() + desc[1:]
    return desc


def on_pre_build(config, **kwargs):
    if not SKILLS_DIR.is_dir():
        return

    skills = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        fm = _parse_frontmatter(skill_md)
        if not fm.get("name"):
            continue
        skills.append(fm)

    if not skills:
        return

    lines = [HEADER]
    for skill in skills:
        name = skill["name"]
        desc = _clean_description(skill.get("description", ""))
        version = skill.get("version", "")

        lines.append(f"## `{name}`\n\n")
        if desc:
            lines.append(f"{desc}\n\n")
        if version:
            lines.append(f"**Version:** {version}\n\n")
        lines.append("---\n\n")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("".join(lines))
