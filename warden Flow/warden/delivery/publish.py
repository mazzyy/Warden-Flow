"""Open a pull request on the developer's repo with the generated DevOps files.

This is how the agent "pushes the workflow back": given a GitHub URL target and a
token with write access, it opens a PR adding the Dockerfile, the CI workflow and
the deploy manifests. The developer reviews and merges — same human gate as the
incident half.

Access: a token with contents+pull_requests write on the target repo, in the
environment as GITHUB_TOKEN (a fine-grained PAT scoped to the repo is enough).
"""

from __future__ import annotations

import os

from warden.delivery.source import parse_repo
from warden.tools.github_client import GitHubClient


def _changes(dockerfile: str, pipeline: str, manifests: dict[str, str]) -> dict[str, str]:
    changes = {"Dockerfile": dockerfile}
    if pipeline:
        changes[".github/workflows/deliver.yml"] = pipeline
    changes.update(manifests or {})
    return changes


async def open_delivery_pr(
    *, target: str, dockerfile: str, pipeline: str, manifests: dict[str, str], base_branch: str = "main"
) -> dict:
    """Open a PR on `target` (a GitHub URL) adding the generated DevOps files."""
    repo = parse_repo(target)
    if not repo:
        return {"error": "PR mode needs a GitHub URL target, e.g. https://github.com/you/your-repo"}

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return {
            "error": "no GITHUB_TOKEN in the environment. Add a token with contents+pull_requests "
            "write on the repo to your .env: GITHUB_TOKEN=github_pat_…"
        }

    client = GitHubClient(repo_full_name=repo, token=token, base_branch=base_branch)
    result = await client.open_delivery_pr(
        title="Add DevOps: Dockerfile, CI pipeline, and deploy manifests",
        body=(
            "Warden Flow generated these from your code:\n"
            "- `Dockerfile` — pinned base, multi-stage, non-root\n"
            "- `.github/workflows/deliver.yml` — build → test → scan → push → deploy\n"
            "- `k8s/` — manifests with resource limits, probes, non-root securityContext"
        ),
        changes=_changes(dockerfile, pipeline, manifests),
    )
    result["repo"] = repo
    return result
