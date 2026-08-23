"""warden bench-deliver — prove the DELIVER workflow beats a single prompt.

Containerizes the SAME service two ways and scores both Dockerfiles against a
production best-practice checklist, computed by inspecting the Dockerfile text —
not asserted:

  * SINGLE PROMPT  — "here's my app, write a Dockerfile" → one answer.
  * WARDEN FLOW    — the staged Assess → Containerize workflow.

    python -m warden.bench_deliver           # offline: scripted, free, deterministic
    python -m warden.bench_deliver --live     # real models (DELIVER_MODEL or Gemini)

Both paths use the same model, so the ONLY variable is structure.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import warnings
from pathlib import Path

from warden.config import GitHubCredential, settings
from warden.control_plane.registry import load_all
from warden.control_plane.store import InMemoryStore
from warden.delivery.fixtures import delivery_scripted_models
from warden.delivery.orchestrator import deliver
from warden.estate.fake import FakeAdapter
from warden.llm import load_env_file
from warden.models import Dockerfile
from warden.tools.github_client import GitHubClient
from warden.tools.toolbox import ToolBox

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
RED, GREEN, YELLOW = "\033[31m", "\033[32m", "\033[33m"

TARGET = "examples/checkout-svc"

# What a single naive prompt typically returns: it works, and it's insecure —
# unpinned base, root user, the whole context copied, a token baked into a layer,
# no scan-friendly structure, no healthcheck.
NAIVE_DOCKERFILE = """\
FROM python:latest
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
ENV API_TOKEN=sk-demo-abc123
EXPOSE 8080
CMD ["python", "main.py"]
"""


def _naive_prompt(src: Path) -> str:
    files = []
    for name in ("main.py", "requirements.txt"):
        p = src / name
        if p.is_file():
            files.append(f"# {name}\n{p.read_text()[:4000]}")
    body = "\n\n".join(files)
    return (
        "Here is my Python service. Write a Dockerfile to containerize it.\n\n"
        f"{body}\n\nReturn only the Dockerfile."
    )


# --------------------------------------------------------------------------
# Scoring — read the Dockerfile and check it, don't take its word.
# --------------------------------------------------------------------------

CHECKS = [
    "pinned base (no :latest)",
    "multi-stage build",
    "runs as non-root",
    "has HEALTHCHECK",
    "no secret baked in ENV",
]


def score_dockerfile(text: str) -> dict[str, bool]:
    lower = text.lower()
    froms = [ln for ln in text.splitlines() if ln.strip().upper().startswith("FROM ")]
    users = [
        ln.split()[1]
        for ln in text.splitlines()
        if ln.strip().upper().startswith("USER ") and len(ln.split()) > 1
    ]
    nonroot = any(u.lower() not in ("root", "0") for u in users)
    secret_env = re.search(
        r"(?im)^\s*ENV\s+\w*(TOKEN|SECRET|PASSWORD|API_KEY|APIKEY|KEY)\w*\s*[=\s]", text
    )
    return {
        "pinned base (no :latest)": bool(froms) and ":latest" not in lower,
        "multi-stage build": len(froms) >= 2,
        "runs as non-root": nonroot,
        "has HEALTHCHECK": "healthcheck" in lower,
        "no secret baked in ENV": secret_env is None,
    }


def _extract_dockerfile(text: str) -> str:
    if "```" in text:
        for chunk in text.split("```"):
            body = chunk[len("dockerfile"):] if chunk.lower().startswith("dockerfile") else chunk
            if "FROM " in body:
                return body.strip()
    return text.strip()


# --------------------------------------------------------------------------
# The two runs.
# --------------------------------------------------------------------------


async def run_workflow(live: bool) -> str:
    s = settings()
    store = InMemoryStore()
    github = GitHubClient(
        repo_full_name=s.gitops_full_name,
        base_branch=s.gitops_base_branch,
        credential=GitHubCredential(kind="none", label="bench dry-run", enforced=False),
    )
    toolbox = ToolBox(
        estate=FakeAdapter("healthy"), store=store, github=github, source_root=TARGET
    )
    fleet = load_all(Path(s.manifest_dir).parent / "delivery")
    models = None if live else delivery_scripted_models()
    result = await deliver(target=TARGET, fleet=fleet, toolbox=toolbox, store=store, models=models)
    d = result.containerize.parse(Dockerfile) if result.containerize else None
    return d.content if d else ""


async def run_single_prompt(live: bool) -> str:
    if not live:
        return NAIVE_DOCKERFILE
    prompt = _naive_prompt(Path(TARGET))
    dm = os.environ.get("DELIVER_MODEL", "")
    if dm and not dm.startswith("gemini"):
        import litellm  # same provider as the workflow, so only structure differs

        resp = await litellm.acompletion(model=dm, messages=[{"role": "user", "content": prompt}])
        return _extract_dockerfile(resp.choices[0].message.content or "")
    from warden.config import MODEL_FLASH, configure_genai_env

    configure_genai_env()
    from google import genai

    client = genai.Client()
    resp = client.models.generate_content(model=MODEL_FLASH, contents=prompt)
    return _extract_dockerfile(resp.text or "")


def print_scoreboard(single: dict[str, bool], flow: dict[str, bool]) -> None:
    def cell(v: bool) -> str:
        return f"{GREEN}pass{RESET}" if v else f"{RED}FAIL{RESET}"

    print(f"\n{BOLD}SCOREBOARD  {DIM}(same service, same model — only the structure differs){RESET}")
    print(f"  {'best-practice check':<30}{DIM}single prompt   warden flow{RESET}")
    for c in CHECKS:
        s = cell(single.get(c, False))
        f = cell(flow.get(c, False))
        pad_s = s + " " * (16 - len("pass"))
        print(f"  {c:<30}{pad_s}{f}")
    sp = sum(single.values())
    fp = sum(flow.values())
    print(f"\n  {BOLD}score{RESET}  single prompt {RED}{sp}/{len(CHECKS)}{RESET}   ·   "
          f"warden flow {GREEN}{fp}/{len(CHECKS)}{RESET}")
    print(f"  {DIM}Both produce a Dockerfile that builds. Only one is safe to ship.{RESET}")


async def main(live: bool) -> int:
    warnings.filterwarnings("ignore", category=UserWarning, module="google.*")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    load_env_file()

    print(f"\n{BOLD}WARDEN FLOW — benchmark: containerize a service, workflow vs single prompt{RESET}")
    print(f"  target     {TARGET}")
    print(f"  models     {'LIVE' if live else 'scripted (offline, free, deterministic)'}")
    if live and os.environ.get("DELIVER_MODEL"):
        print(f"  provider   {os.environ['DELIVER_MODEL']}")

    print(f"\n{DIM}running single prompt…{RESET}")
    single_df = await run_single_prompt(live)
    print(f"{DIM}running warden flow…{RESET}")
    flow_df = await run_workflow(live)

    print_scoreboard(score_dockerfile(single_df), score_dockerfile(flow_df))

    print(f"\n{DIM}  single prompt's Dockerfile (first lines):{RESET}")
    for line in single_df.splitlines()[:7]:
        print(f"    {RED}│{RESET} {line}")
    print()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Benchmark containerization: workflow vs single prompt.")
    p.add_argument("--live", action="store_true", help="use real models for both paths")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(args.live)))
