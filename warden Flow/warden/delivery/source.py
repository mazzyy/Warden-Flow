"""Resolve a delivery target to a local directory the workflow can read.

A target is either a local path (used as-is) or a git URL, which is shallow-cloned
to a temp directory. For a private github.com repo, a GITHUB_TOKEN in the
environment is injected into the clone URL so the agent can reach it — "give the
agent access" is a real credential, not just typing the URL.
"""

from __future__ import annotations

import os
import subprocess
import tempfile


def is_remote(target: str) -> bool:
    return target.startswith(("http://", "https://", "git@", "ssh://")) or target.endswith(".git")


def resolve_source(target: str) -> str:
    """Return a local directory for `target`, cloning it first if it is a git URL."""
    if not is_remote(target):
        return target

    url = target
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token and url.startswith("https://github.com/"):
        # Inject the token so private repos clone. It never lands on disk — it is
        # only in the argv of this one subprocess.
        url = url.replace("https://", f"https://x-access-token:{token}@", 1)

    dest = tempfile.mkdtemp(prefix="warden-src-")
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", url, dest],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if proc.returncode != 0:
        err = proc.stderr.strip().replace(token, "***") if token else proc.stderr.strip()
        raise RuntimeError(f"could not clone {target}: {err[:300]}")
    return dest
