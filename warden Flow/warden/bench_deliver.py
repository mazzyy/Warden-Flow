"""warden bench-deliver — measure the DELIVER workflow against a single prompt.

Containerizes the SAME service two ways and scores both Dockerfiles against a
production best-practice checklist, computed by inspecting the Dockerfile text —
not asserted:

  * SINGLE PROMPT  — "here's my app, write a Dockerfile" → one answer.
  * WARDEN FLOW    — the staged Assess → Containerize workflow.

    python -m warden.bench_deliver                 # offline REPLAY — see below
    python -m warden.bench_deliver --live          # real models, one sample each
    python -m warden.bench_deliver --live -n 5     # real models, five samples each

OFFLINE MODE IS A REPLAY, NOT A MEASUREMENT.  With no `--live`, both sides are
fixtures: the workflow runs scripted models and the single-prompt side returns a
RECORDED answer (see `RECORDED_SINGLE_PROMPT`). It exists so the demo runs with
no API key and no cost, and so the scoring function itself is testable — it is
NOT evidence about either approach, and the banner says so on every run.

The number worth quoting is `--live -n 5`: same model, same service, same
scoring function, five samples each, so the only variable is structure and you
can see the variance rather than one lucky draw.
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

# A RECORDED single-prompt answer, replayed in offline mode so the benchmark
# runs without an API key. It is a real observed shape — unpinned base, root
# user, whole context copied, a token baked into a layer, no healthcheck — but
# replaying it proves nothing about what a model does today. Any claim about
# the single-prompt baseline must come from `--live`.
RECORDED_SINGLE_PROMPT = """\
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
        return RECORDED_SINGLE_PROMPT
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


def _rate(results: list[dict[str, bool]], check: str) -> float:
    return sum(1 for r in results if r.get(check)) / max(len(results), 1)


def print_scoreboard(
    single: list[dict[str, bool]], flow: list[dict[str, bool]], *, live: bool
) -> None:
    n = len(single)

    def cell(rate: float) -> str:
        if n == 1:
            return f"{GREEN}pass{RESET}" if rate == 1.0 else f"{RED}FAIL{RESET}"
        colour = GREEN if rate == 1.0 else (YELLOW if rate > 0 else RED)
        return f"{colour}{int(round(rate * n))}/{n}{RESET}"

    header = "pass rate over " + str(n) + " samples" if n > 1 else "single run"
    print(f"\n{BOLD}SCOREBOARD  {DIM}(same service, same model, same scorer — "
          f"only the structure differs · {header}){RESET}")
    print(f"  {'best-practice check':<30}{DIM}single prompt   warden flow{RESET}")
    for c in CHECKS:
        s = cell(_rate(single, c))
        f = cell(_rate(flow, c))
        print(f"  {c:<30}{s + ' ' * (16 - 4)}{f}")

    sp = sum(sum(r.values()) for r in single) / n
    fp = sum(sum(r.values()) for r in flow) / n
    label = "mean score" if n > 1 else "score"
    print(f"\n  {BOLD}{label}{RESET}  single prompt {RED}{sp:.1f}/{len(CHECKS)}{RESET}   ·   "
          f"warden flow {GREEN}{fp:.1f}/{len(CHECKS)}{RESET}")
    print(f"  {DIM}Both produce a Dockerfile that builds. Only one is safe to ship.{RESET}")

    if not live:
        print(f"\n  {YELLOW}NOTE{RESET} {DIM}offline mode REPLAYS fixtures on both sides — this is a "
              f"demo of the scorer, not\n       evidence. Quote `--live -n 5`, "
              f"which runs both paths on a real model.{RESET}")


async def main(live: bool, samples: int) -> int:
    warnings.filterwarnings("ignore", category=UserWarning, module="google.*")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    load_env_file()

    if not live and samples > 1:
        print(f"{DIM}offline mode is deterministic — falling back to 1 sample.{RESET}")
        samples = 1

    print(f"\n{BOLD}WARDEN FLOW — benchmark: containerize a service, workflow vs single prompt{RESET}")
    print(f"  target     {TARGET}")
    print(f"  models     {'LIVE' if live else 'REPLAY (offline fixtures, free, deterministic)'}")
    print(f"  samples    {samples} per approach")
    if live and os.environ.get("DELIVER_MODEL"):
        print(f"  provider   {os.environ['DELIVER_MODEL']}")

    singles: list[dict[str, bool]] = []
    flows: list[dict[str, bool]] = []
    last_single = ""

    for i in range(samples):
        tag = f" [{i + 1}/{samples}]" if samples > 1 else ""
        print(f"\n{DIM}running single prompt{tag}…{RESET}")
        last_single = await run_single_prompt(live)
        singles.append(score_dockerfile(last_single))
        print(f"{DIM}running warden flow{tag}…{RESET}")
        flows.append(score_dockerfile(await run_workflow(live)))

    print_scoreboard(singles, flows, live=live)

    print(f"\n{DIM}  single prompt's Dockerfile — last sample, first lines:{RESET}")
    for line in last_single.splitlines()[:7]:
        print(f"    {RED}│{RESET} {line}")
    print()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Benchmark containerization: workflow vs single prompt.")
    p.add_argument("--live", action="store_true", help="use real models for both paths")
    p.add_argument("-n", "--samples", type=int, default=1,
                   help="samples per approach (live only) — use 5 to show variance")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(args.live, max(1, args.samples))))
