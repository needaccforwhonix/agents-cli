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

"""Resolve extension references to commit SHAs and vendor extension directories."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml
from filelock import FileLock, Timeout

from google.agents.cli._runner import run_resolved
from google.agents.cli.extension._paths import git_cache_dir_name, git_cache_root
from google.agents.cli.extension._refs import ExtensionRef
from google.agents.cli.extension._spec import EXTENSION_FILE

# Only a full 40-char commit SHA is unambiguous. A short/partial hex string
# could instead be a branch or tag named like hex (e.g. "cafe123"), so anything
# shorter than 40 goes through ls-remote ref resolution rather than being
# treated as an already-resolved commit.
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# An extension name becomes a directory component under the vendoring root, so it
# must not contain path separators or traversal — reject anything else.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_extension_name(name: str) -> str:
    """Return ``name`` if safe as a single path component, else raise.

    Guards the vendoring path (``dest_root / name``, which ``_replace_tree``
    ``rmtree``s and recreates) against a malicious ``name:`` (e.g. ``../../x``)
    read from an upstream extension file or a committed manifest.
    """
    if name in (".", "..") or not _SAFE_NAME_RE.match(name):
        raise ResolverError(
            f"unsafe extension name {name!r}: use only letters, digits, '.', '_', '-'."
        )
    return name


# Seconds to wait for the shared git-cache lock before giving up.
_CACHE_LOCK_TIMEOUT_SECONDS = 120

# Records what a vendored copy was materialized from, so sync can detect a
# stale or partial copy (dir exists but doesn't match its source) instead of
# trusting mere directory existence.
STAMP_FILE = ".agents-cli-extension-sha"

# Recorded as the pin of a `local@` extension, which has no commit to point at.
LOCAL_SHA = "local"

# Skipped when fingerprinting a local source: neither is part of the extension,
# both churn constantly, and `.git` can dwarf the code beside it.
_FINGERPRINT_EXCLUDES = frozenset({".git", "__pycache__"})


class ResolverError(Exception):
    """Raised when an extension cannot be resolved or vendored."""


def read_stamp(extension_dir: Path) -> str | None:
    """Return what an extension dir was materialized from, or None if unstamped."""
    stamp = extension_dir / STAMP_FILE
    if not stamp.exists():
        return None
    return stamp.read_text(encoding="utf-8").strip() or None


def expected_stamp(ref: ExtensionRef, sha: str) -> str:
    """Return the stamp a freshly materialized copy of ``ref`` would carry.

    For a git ref that is the pinned SHA. A ``local@`` ref has no commit to pin —
    its recorded pin is the constant ``LOCAL_SHA`` — so its copy is stamped with a
    hash of the source tree instead. Comparing that hash is what lets sync notice
    edits to a local source; comparing the pin would only match the sentinel
    against itself and never refresh.
    """
    if ref.kind != "local":
        return sha
    return _fingerprint(_local_source_dir(ref))


def _fingerprint(root: Path) -> str:
    """Return a hash of the name and contents of every file under ``root``.

    Walked in sorted order and keyed on POSIX-style relative paths, so a given
    tree hashes identically across runs and platforms. Symlinks are skipped to
    match the vendored copy (see ``_skip_symlinks``), which also keeps the hash
    from depending on a file the copy never contains.

    Scanned with ``os.scandir``, whose entries answer "directory or symlink?"
    from the directory read itself: one syscall per directory rather than a
    ``stat`` per name. An unreadable directory raises rather than being skipped,
    since a tree walked only in part hashes the same after a change inside the
    part that was missed.
    """
    digest = hashlib.sha256()
    # (directory, its POSIX path relative to root). A stack, so a deep source
    # tree cannot exhaust the interpreter's recursion limit.
    stack: list[tuple[str, str]] = [(str(root), "")]
    try:
        while stack:
            directory, rel_dir = stack.pop()
            subdirs: list[os.DirEntry[str]] = []
            files: list[os.DirEntry[str]] = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name not in _FINGERPRINT_EXCLUDES:
                            subdirs.append(entry)
                    else:
                        files.append(entry)
            prefix = f"{rel_dir}/" if rel_dir else ""
            for entry in sorted(files, key=lambda e: e.name):
                with open(entry.path, "rb") as f:
                    contents = hashlib.file_digest(f, "sha256").hexdigest()
                digest.update(f"{prefix}{entry.name}\0{contents}\0".encode())
            # Reversed, so popping visits the subdirectories in sorted order.
            for entry in sorted(subdirs, key=lambda e: e.name, reverse=True):
                stack.append((entry.path, f"{prefix}{entry.name}"))
    except OSError as e:
        raise ResolverError(f"could not read local extension source {root}: {e}") from e
    return digest.hexdigest()


def _local_source_dir(ref: ExtensionRef) -> Path:
    """Return the directory a ``local@`` ref selects, or raise if it is unusable."""
    src = ref.local_path
    if src is None or not src.exists():
        raise ResolverError(f"local extension path not found: {ref.local_path}.")
    sub = src / ref.selector if ref.selector else src
    if not (sub / EXTENSION_FILE).exists():
        raise ResolverError(f"{sub} has no {EXTENSION_FILE}.")
    return sub


def _https_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def _clone_url(ref: ExtensionRef) -> str:
    """Return the URL git should clone or query for a non-local ref."""
    if ref.url is not None:
        return ref.url
    if ref.repo is None:
        raise ResolverError(f"cannot resolve ref {ref.raw!r}: repo is not set.")
    return _https_url(ref.repo)


def _git(*args: str) -> subprocess.CompletedProcess:
    """Run a git command with output captured (no shell, no PATH resolution)."""
    return run_resolved(
        ["git", *args],
        resolve_executable=False,
        capture_output=True,
        text=True,
    )


def resolve_sha(ref: ExtensionRef) -> str:
    """Resolve an ExtensionRef to an exact commit SHA.

    For local refs returns the sentinel ``LOCAL_SHA`` (unpinned).
    For every other ref runs ``git ls-remote`` unless the caller
    already supplied a full hex SHA.
    """
    if ref.kind == "local":
        return LOCAL_SHA
    if ref.ref and _SHA_RE.match(ref.ref):
        return ref.ref
    target = ref.ref or "HEAD"
    result = _git("ls-remote", _clone_url(ref), target)
    if result.returncode != 0 or not result.stdout.strip():
        raise ResolverError(
            f"could not resolve {target!r} in {ref.repo!r}; check the repo and ref."
        )
    return result.stdout.split()[0]


def _extension_name_from_dir(extension_dir: Path, fallback: str) -> str:
    spec_path = extension_dir / EXTENSION_FILE
    if spec_path.exists():
        try:
            with open(spec_path, encoding="utf-8") as f:
                data: Any = yaml.safe_load(f) or {}
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                return str(data["name"])
        except (OSError, RecursionError, UnicodeDecodeError, yaml.YAMLError):
            # Best-effort name detection only: fall back to the caller's name if
            # the file is unreadable/malformed. The loader reports it properly —
            # warned about and skipped on load, fatal for `add`/`update`.
            pass
    return fallback


def _skip_symlinks(directory: str, names: list[str]) -> set[str]:
    """Names in ``directory`` that are symlinks, for ``copytree(ignore=...)``."""
    skipped = {n for n in names if Path(directory, n).is_symlink()}
    for name in sorted(skipped):
        logging.warning("Skipping symlink in extension source: %s", Path(directory, name))
    return skipped


def _replace_tree(src: Path, dest: Path) -> None:
    """Replace ``dest`` with a copy of ``src``, leaving it alone if the copy fails."""
    # Copy alongside and swap, so an unreadable source cannot delete the working
    # copy on its way to failing. shutil.Error is an OSError.
    staged = dest.parent / f".{dest.name}.incoming"
    try:
        shutil.rmtree(staged, ignore_errors=True)
        # Never follow symlinks out of an extension: copytree would otherwise
        # dereference `notes.md -> ~/.ssh/id_rsa` into a real file in the
        # project, where it gets committed (CWE-59).
        shutil.copytree(src, staged, ignore=_skip_symlinks)
        if dest.exists():
            shutil.rmtree(dest)
        staged.rename(dest)
    except OSError as e:
        shutil.rmtree(staged, ignore_errors=True)
        raise ResolverError(f"could not copy {src} into {dest}: {e}") from e


def _write_stamp(extension_dir: Path, sha: str) -> None:
    """Record the SHA the copy was materialized from (written last, post-copy)."""
    (extension_dir / STAMP_FILE).write_text(sha, encoding="utf-8")


def materialize(
    ref: ExtensionRef,
    sha: str,
    dest_root: Path,
    *,
    name: str | None = None,
) -> tuple[str, Path]:
    """Vendor an extension directory into ``dest_root/<extension_name>``.

    Returns ``(extension_name, extension_dir)``.
    For ``local@`` refs, copies from the local path.
    For git refs, clones/reuses the cache and checks out ``sha``.

    When ``name`` is provided the vendored directory is placed at
    ``dest_root/<name>`` (the caller's stable id) and that name is returned,
    regardless of what the upstream ``agents-cli-extension.yaml`` declares.  This
    prevents an extension rename upstream from silently relocating (and losing) the
    vendored copy.
    """
    dest_root.mkdir(parents=True, exist_ok=True)

    if ref.kind == "local":
        sub = _local_source_dir(ref)
        spec_name = _extension_name_from_dir(sub, ref.selector or sub.name)
        resolved_name = validate_extension_name(name if name is not None else spec_name)
        extension_dir = dest_root / resolved_name
        # Fingerprinted before the copy, so a source edited while it is being
        # copied leaves the older stamp and the next sync redoes the copy,
        # rather than blessing a tree that is half of each.
        stamp = _fingerprint(sub)
        _replace_tree(sub, extension_dir)
        _write_stamp(extension_dir, stamp)
        return resolved_name, extension_dir

    checkout = _checkout(ref, sha)
    if ref.kind == "first_party":
        # First-party extensions live under extensions/<selector>/ in the repo.
        sub = checkout / "extensions" / ref.selector if ref.selector else checkout
    else:
        sub = checkout / ref.selector if ref.selector else checkout
    if not (sub / EXTENSION_FILE).exists():
        raise ResolverError(
            f"{ref.repo}#{ref.selector or ''} has no {EXTENSION_FILE} at the pinned commit."
        )
    spec_name = _extension_name_from_dir(
        sub, ref.selector or (ref.repo.split("/")[-1] if ref.repo else "extension")
    )
    resolved_name = validate_extension_name(name if name is not None else spec_name)
    extension_dir = dest_root / resolved_name
    _replace_tree(sub, extension_dir)
    _write_stamp(extension_dir, sha)
    return resolved_name, extension_dir


def _checkout(ref: ExtensionRef, sha: str) -> Path:
    """Clone (or reuse) the repo in the shared cache and check out ``sha``.

    Returns the worktree root path.
    """
    cache = git_cache_root()
    cache.mkdir(parents=True, exist_ok=True)
    if ref.repo is None:
        raise ResolverError(f"cannot checkout ref {ref.raw!r}: repo is not set.")
    repo_dir = cache / git_cache_dir_name(ref.repo, ref.url)
    url = _clone_url(ref)

    # The cache is shared across processes and checkout mutates a single working
    # tree, so serialize all git operations on this repo with a per-repo lock.
    try:
        lock = FileLock(
            str(cache / f"{repo_dir.name}.lock"),
            timeout=_CACHE_LOCK_TIMEOUT_SECONDS,
        )
        with lock:
            return _checkout_locked(repo_dir, url, ref.repo, sha)
    except Timeout as e:
        raise ResolverError(
            f"timed out waiting for the extension cache lock for {ref.repo}; "
            "another agents-cli process may be resolving extensions."
        ) from e


def _checkout_locked(repo_dir: Path, url: str, repo: str, sha: str) -> Path:
    if not (repo_dir / ".git").exists():
        res = _git("clone", "--quiet", url, str(repo_dir))
        if res.returncode != 0:
            raise ResolverError(f"git clone failed for {repo}: {res.stderr.strip()}")

    fetch = _git("-C", str(repo_dir), "fetch", "--quiet", "origin", sha)
    # Some hosts reject fetching an arbitrary SHA; fall back to a full fetch.
    if fetch.returncode != 0:
        _git("-C", str(repo_dir), "fetch", "--quiet", "--all")

    checkout = _git("-C", str(repo_dir), "checkout", "--quiet", sha)
    if checkout.returncode != 0:
        raise ResolverError(f"git checkout {sha} failed: {checkout.stderr.strip()}")
    return repo_dir
