"""Ship one service through the DELIVER workflow, printed as a readable trace.

    python -m warden.deliver              # offline: scripted models, free
    python -m warden.deliver --live       # real models (Gemini, or DELIVER_MODEL)

Set DELIVER_MODEL=azure/<deployment> (or openai/..., anthropic/...) to run the
delivery nodes on a different provider. Offline needs no key.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import warnings
from pathlib import Path

from warden.config import GitHubCredential, configure_genai_env, settings
from warden.control_plane.budget import estimate_usd
from warden.control_plane.registry import load_all
from warden.control_plane.store import InMemoryStore
from warden.delivery.fixtures import delivery_scripted_models
from warden.delivery.orchestrator import deliver
from warden.estate.fake import FakeAdapter
from warden.llm import load_env_file
from warden.models import Decision, DeployPlan, Dockerfile, Pipeline, RepoProfile, VerifyReport
from warden.tools.github_client import GitHubClient
from warden.tools.toolbox import ToolBox

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"
RED, GREEN, YELLOW, BLUE, CYAN = "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[36m"


def rule(title: str = "") -> None:
    print(f"\n{DIM}{'─' * 78}{RESET}")
    if title:
        print(f"{BOLD}{title}{RESET}")


def delivery_fleet() -> dict:
    # The delivery nodes live in manifests/delivery/, separate from the incident
    # fleet in manifests/agents/, so each workflow loads only its own nodes.
    return load_all(Path(settings().manifest_dir).parent / "delivery")


async def main(
    live: bool, target: str, write: bool = False, apply_it: bool = False, pr: bool = False
) -> int:
    warnings.filterwarnings("ignore", category=UserWarning, module="google.*")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    load_env_file()  # bridge .env provider creds (AZURE_*, DELIVER_MODEL) into os.environ
    s = settings()

    rule("WARDEN FLOW — deliver a service")
    print(f"  target     {target}")
    print(f"  models     {'LIVE' if live else 'scripted (offline, free)'}")
    import os

    if live and os.environ.get("DELIVER_MODEL"):
        print(f"  provider   {os.environ['DELIVER_MODEL']}")

    if live:
        # A non-Gemini DELIVER_MODEL (azure/…, openai/…, anthropic/…) authenticates
        # through LiteLLM's own env vars, so Google/Vertex credentials aren't needed.
        dm = os.environ.get("DELIVER_MODEL", "")
        if not dm or dm.startswith("gemini"):
            try:
                configure_genai_env()
            except Exception as exc:
                print(f"\n{RED}{exc}{RESET}\n")
                return 2

    estate = FakeAdapter("healthy")
    store = InMemoryStore()
    github = GitHubClient(
        repo_full_name=s.gitops_full_name,
        base_branch=s.gitops_base_branch,
        credential=GitHubCredential(kind="none", label="deliver dry-run", enforced=False),
    )
    from warden.delivery.source import is_remote, resolve_source

    if is_remote(target):
        print(f"  {DIM}cloning {target}…{RESET}")
    source_dir = resolve_source(target)  # clones a git URL to a temp dir
    toolbox = ToolBox(
        estate=estate, store=store, github=github, alert_context={}, source_root=source_dir
    )
    fleet = delivery_fleet()
    models = None if live else delivery_scripted_models()

    result = await deliver(target=target, fleet=fleet, toolbox=toolbox, store=store, models=models)

    for agent_run in result.runs:
        r = agent_run.run
        rule(f"{r.agent.upper()}  {DIM}{r.model}{RESET}")
        audit = [a for a in await store.list_audit() if a.run_id == r.id]
        for a in audit:
            mark = f"{GREEN}✓{RESET}" if a.decision is Decision.allow else f"{RED}✗ DENIED{RESET}"
            print(f"  {mark} {a.tool}{DIM} ({a.latency_ms}ms){RESET}")

        if r.agent == "assess":
            p = agent_run.parse(RepoProfile)
            if p:
                print(f"  {BLUE}language{RESET}   {p.language} ({p.framework})")
                print(f"  {BLUE}entrypoint{RESET} {p.entrypoint}")
                print(f"  {BLUE}ports{RESET}      {p.ports}")
                print(f"  {BLUE}build{RESET}      {p.build_system}")
        elif r.agent == "containerize":
            d = agent_run.parse(Dockerfile)
            if d:
                print(f"  {BLUE}base{RESET}       {d.base_image}   "
                      f"multistage={d.multistage}  non-root={d.runs_as_nonroot}")
                print(f"  {CYAN}security:{RESET}")
                for note in d.security_notes:
                    print(f"    {GREEN}✓{RESET} {note}")
                print(f"\n{DIM}  ── generated Dockerfile ──{RESET}")
                for line in d.content.splitlines():
                    print(f"  {DIM}│{RESET} {line}")
        elif r.agent == "pipeline":
            p = agent_run.parse(Pipeline)
            if p:
                print(f"  {BLUE}stages{RESET}     {' → '.join(p.stages)}")
                print(f"  {DIM}{p.rationale}{RESET}")
        elif r.agent == "deploy_plan":
            dp = agent_run.parse(DeployPlan)
            if dp:
                print(f"  {BLUE}manifests{RESET}  {', '.join(m.path for m in dp.manifests) or '(none)'}")
                print(f"  {BLUE}strategy{RESET}   {dp.strategy}")
                print(f"  {BLUE}rollback{RESET}   {dp.rollback}")
        elif r.agent == "verify_artifacts":
            v = agent_run.parse(VerifyReport)
            if v:
                verdict = f"{GREEN}PASSED{RESET}" if v.passed else f"{RED}FAILED{RESET}"
                print(f"  verdict    {verdict}")
                for c in v.checks:
                    print(f"    {GREEN}✓{RESET} {c}")
                for issue in v.issues:
                    print(f"    {RED}✗{RESET} {issue}")

        print(f"  {DIM}{r.total_tokens} tokens · ~${estimate_usd(r.model, r.prompt_tokens, r.candidates_tokens):.4f}{RESET}")

    rule("DELIVERY")
    print(f"  {result.id}  target={result.target}")
    print(f"  {result.total_tokens} tokens across {len(result.runs)} nodes")
    if result.stopped_at:
        print(f"  {YELLOW}stopped at {result.stopped_at}{RESET}")
    else:
        print(f"  {GREEN}Dockerfile generated and ready for human review.{RESET}")

    # -- open a pull request on the target repo with the generated files -----
    if pr and not result.stopped_at:
        from warden.delivery.publish import open_delivery_pr

        df = result.containerize.parse(Dockerfile) if result.containerize else None
        pl = result.pipeline.parse(Pipeline) if result.pipeline else None
        dp = result.deploy_plan.parse(DeployPlan) if result.deploy_plan else None
        rule("PULL REQUEST")
        if df is None:
            print(f"  {YELLOW}nothing to propose — the workflow stopped early{RESET}")
        else:
            outcome = await open_delivery_pr(
                target=target,
                dockerfile=df.content,
                pipeline=pl.content if pl else "",
                manifests=dp.as_dict() if dp else {},
            )
            if outcome.get("error"):
                print(f"  {RED}{outcome.get('detail') or outcome['error']}{RESET}")
            elif outcome.get("dry_run"):
                print(f"  {YELLOW}dry run — would open a PR on {outcome.get('repo')}{RESET}")
            else:
                print(f"  {GREEN}{outcome['pr_url']}{RESET}")
                created = outcome.get("files_created", [])
                if created:
                    print(f"  {DIM}added: {', '.join(created)}{RESET}")
                for sk in outcome.get("skipped", []):
                    print(f"  {YELLOW}skipped {sk['path']} — {sk['reason']}{RESET}")
                if any(".github/workflows" in s["path"] for s in outcome.get("skipped", [])):
                    print(f"  {DIM}(add the 'Workflows' permission to your token to include the CI file){RESET}")

    # -- write artifacts into the repo, and (optionally) build/push/deploy ----
    if (write or apply_it) and not result.stopped_at:
        import os as _os

        from warden.delivery.apply import run_apply, write_artifacts

        df = result.containerize.parse(Dockerfile) if result.containerize else None
        pl = result.pipeline.parse(Pipeline) if result.pipeline else None
        dp = result.deploy_plan.parse(DeployPlan) if result.deploy_plan else None
        if df:
            written = write_artifacts(
                source_dir, df.content, pl.content if pl else "", dp.as_dict() if dp else {}
            )
            rule("ARTIFACTS WRITTEN")
            for w in written:
                print(f"  {GREEN}✓{RESET} {w}")
            print(f"  {DIM}into {source_dir}{RESET}")

            app_name = _os.path.basename(_os.path.abspath(source_dir)) or "app"
            outcome = run_apply(
                source_dir=source_dir, app=app_name, tag=result.id.lower(), execute=apply_it
            )
            rule("APPLY — build · push · deploy" + ("  (executed)" if apply_it else "  (plan)"))
            for cmd in outcome.get("plan", []):
                print(f"  {DIM}$ {cmd}{RESET}")
            for r2 in outcome.get("results", []):
                mark = f"{GREEN}✓{RESET}" if r2["ok"] else f"{RED}✗{RESET}"
                print(f"  {mark} {r2['step']}  {DIM}{r2['cmd']}{RESET}")
                if not r2["ok"]:
                    print(f"      {RED}{r2['output']}{RESET}")
            if outcome.get("reason"):
                print(f"  {YELLOW}{outcome['reason']}{RESET}")

    if not live:
        print(f"\n  {DIM}Run with --live for real models. Set DELIVER_MODEL for Azure/OpenAI/Anthropic.{RESET}")
    print()
    return 0


def _entry(default_target: str) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true", help="use real models instead of scripted")
    p.add_argument("--target", default=default_target,
                   help="local directory (or git URL) to deliver; defaults to the current repo")
    p.add_argument("--write", action="store_true",
                   help="write the generated Dockerfile / pipeline / manifests into the repo")
    p.add_argument("--apply", action="store_true",
                   help="write, then build, push to ACR and deploy (needs ACR_* creds in env)")
    p.add_argument("--pr", action="store_true",
                   help="open a pull request on the target GitHub repo with the generated files "
                        "(needs GITHUB_TOKEN with write access)")
    args = p.parse_args()
    raise SystemExit(
        asyncio.run(main(args.live, args.target, write=args.write, apply_it=args.apply, pr=args.pr))
    )


def cli() -> None:
    """Console entry (`warden-deliver`): defaults to the current directory, so a
    developer runs it from inside their own repo — no clone, no path to type."""
    _entry(".")


if __name__ == "__main__":  # python -m warden.deliver: keeps the bundled sample default
    _entry("examples/checkout-svc")
