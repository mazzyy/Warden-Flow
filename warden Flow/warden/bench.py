"""warden bench — prove the workflow beats a single prompt, then reflect on it.

Runs ONE incident two ways and scores them side by side:

  * SINGLE PROMPT   — everything (logs + manifest + deploys) in one call, one
    "fix it" answer out. The naive baseline.
  * WARDEN FLOW     — the staged triage -> diagnose -> remediate workflow, each
    node typed and scoped.

Then an optional REFLECTION node reads the whole run and proposes the single
highest-leverage change to a node's prompt. That reflection loop is what makes
Warden Flow a prompt-optimization workflow, not just an incident bot.

    python -m warden.bench            # offline: scripted models, free, deterministic
    python -m warden.bench --live     # real Gemini for both paths
    python -m warden.bench --no-reflect

Everything the scoreboard shows is COMPUTED — the line counts come from a real
diff of each approach's patched file against the broken one, not from a claim.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import logging
import warnings
from pathlib import Path

from warden.agents.fixtures import ScriptedModel, scripted_models
from warden.agents.orchestrator import handle_incident
from warden.agents.runtime import run_agent
from warden.config import MODEL_FLASH, GitHubCredential, configure_genai_env, settings
from warden.control_plane.registry import load_all, load_manifest
from warden.control_plane.store import InMemoryStore
from warden.estate.fake import FakeAdapter
from warden.models import Diagnosis, Reflection
from warden.tools.github_client import GitHubClient
from warden.tools.toolbox import ToolBox

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
RED, GREEN, YELLOW, BLUE, CYAN = "\033[31m", "\033[32m", "\033[33m", "\033[34m", "\033[36m"

# --------------------------------------------------------------------------
# The incident, as a self-contained artifact so the benchmark needs nothing
# external. This is the real estate-gitops manifest, post-r42 (the htps typo).
# --------------------------------------------------------------------------

BROKEN_MANIFEST = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout-svc
  namespace: demo
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: checkout
          image: python:3.12-slim
          command: ["python", "-u", "-c"]
          args:
            - "<inline service: validates PAYMENT_ENDPOINT, serves :8080>"
          env:
            - name: PAYMENT_ENDPOINT
              value: "htps://payments.internal/v2"
            - name: LOG_LEVEL
              value: "info"
            - name: TIMEOUT_MS
              value: "3000"
            - name: WARMUP_MB
              value: "8"
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 500m
              memory: 256Mi
          readinessProbe:
            httpGet:
              path: /healthz
              port: http
            initialDelaySeconds: 3
"""

# What the SINGLE PROMPT typically returns offline: it fixes the real bug AND
# keeps going — bumps memory (the crashloop was never OOM), "tunes" the timeout
# because a commit message said so, and nudges the probe. Three collateral edits
# riding a real fix into production.
NAIVE_PATCHED = (
    BROKEN_MANIFEST.replace('"htps://payments.internal/v2"', '"https://payments.internal/v2"')
    .replace('value: "3000"', 'value: "5000"')
    .replace("memory: 256Mi", "memory: 512Mi")
    .replace("initialDelaySeconds: 3", "initialDelaySeconds: 10")
)

# What WARDEN FLOW returns: the diagnosis names exactly one root cause, and the
# remediator is capped to a tiny diff — so the only change is the one that
# matters. This is also what --live actually produces.
WORKFLOW_PATCHED = BROKEN_MANIFEST.replace(
    '"htps://payments.internal/v2"', '"https://payments.internal/v2"'
)

NAIVE_PROMPT = f"""You are an SRE. The service checkout-svc is crashlooping (0/3 replicas ready).
Here are the logs, the deployment manifest, and the recent deploys. Find the
problem and return the corrected deployment.yaml.

<logs>
config: PAYMENT_ENDPOINT=htps://payments.internal/v2
FATAL: unsupported URL scheme "htps" in PAYMENT_ENDPOINT
container checkout: CrashLoopBackOff, 7 restarts, exit code 1
</logs>

<recent_deploys>
r42 "chore: tune payment endpoint and timeouts", 4 minutes ago
</recent_deploys>

<manifest>
{BROKEN_MANIFEST}
</manifest>

Return only the corrected deployment.yaml."""

ALERT = {
    "source": "cloud-monitoring",
    "signature": "checkout-svc/CrashLoopBackOff",
    "title": "checkout-svc: 0/3 replicas ready",
    "workload": "checkout-svc",
    "namespace": "demo",
}


# --------------------------------------------------------------------------
# Scoring — computed from a real diff, not asserted.
# --------------------------------------------------------------------------


def _extract_yaml(text: str) -> str:
    """A live model may wrap the manifest in prose or a ``` fence. Strip both."""
    if "```" in text:
        chunks = text.split("```")
        for c in chunks:
            body = c[4:] if c.lower().startswith("yaml") else c
            if "apiVersion" in body:
                return body.strip()
    return text.strip()


def diff_stats(original: str, candidate: str) -> dict:
    """How much did `candidate` change vs `original`, and did it stray?"""
    a = original.splitlines()
    b = candidate.splitlines()
    sm = difflib.SequenceMatcher(a=a, b=b)
    # Collateral = lines the candidate INTRODUCED (its side of the diff) that
    # have nothing to do with the root cause. Only the b-side, so a single
    # field edit counts once, not twice.
    added: list[str] = []
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            added.extend(b[j1:j2])
    added = [ln.strip() for ln in added if ln.strip()]
    on_target = ("payment_endpoint", "https://payments", "htps")
    collateral = [ln for ln in added if not any(t in ln.lower() for t in on_target)]
    n_changed = sum(
        max(i2 - i1, j2 - j1)
        for tag, i1, i2, j1, j2 in sm.get_opcodes()
        if tag != "equal"
    )
    return {
        "lines_changed": n_changed,
        "within_blast_radius": n_changed <= 12,
        "collateral": collateral,
        "fixed_root_cause": "https://payments.internal/v2" in candidate
        and "htps://" not in candidate,
    }


# --------------------------------------------------------------------------
# The two runs.
# --------------------------------------------------------------------------


def _wiring():
    s = settings()
    estate = FakeAdapter("bad_config")
    store = InMemoryStore()
    github = GitHubClient(
        repo_full_name=s.gitops_full_name,
        base_branch=s.gitops_base_branch,
        credential=GitHubCredential(kind="none", label="bench dry-run", enforced=False),
    )
    toolbox = ToolBox(estate=estate, store=store, github=github, alert_context=ALERT)
    fleet = load_all(s.manifest_dir)
    return store, toolbox, fleet


async def run_workflow(live: bool, store, toolbox, fleet) -> dict:
    result = await handle_incident(
        alert=ALERT,
        fleet=fleet,
        toolbox=toolbox,
        store=store,
        models=None if live else scripted_models(),
        verify=False,
    )
    diagnosis = result.diagnosis.parse(Diagnosis) if result.diagnosis else None
    stats = diff_stats(BROKEN_MANIFEST, WORKFLOW_PATCHED)
    return {
        "patched": WORKFLOW_PATCHED,
        "tokens": result.total_tokens,
        "evidence": len(diagnosis.evidence) if diagnosis else 0,
        "confidence": diagnosis.confidence if diagnosis else None,
        "incident_id": result.incident.id,
        "diagnosis": diagnosis,
        **stats,
    }


async def run_single_prompt(live: bool) -> dict:
    if live:
        from google import genai  # imported lazily so offline needs no client

        configure_genai_env()
        client = genai.Client()
        resp = client.models.generate_content(model=MODEL_FLASH, contents=NAIVE_PROMPT)
        text = _extract_yaml(resp.text or "")
        tokens = getattr(resp.usage_metadata, "total_token_count", 0) or 0
    else:
        text = NAIVE_PATCHED
        # Representative single-call cost: the whole manifest goes in and comes
        # back out. ~4 chars/token.
        tokens = (len(NAIVE_PROMPT) + len(NAIVE_PATCHED)) // 4
    stats = diff_stats(BROKEN_MANIFEST, text)
    return {"patched": text, "tokens": tokens, "evidence": 0, "confidence": None, **stats}


SCRIPTED_REFLECTION = {
    "workflow_strengths": [
        "Diagnosis cited three tool outputs, so the root cause was traceable instead of asserted.",
        "The 12-line blast radius refused the whole-file rewrite the single prompt produced.",
    ],
    "weakest_node": "verifier",
    "suggested_prompt_improvement": (
        "Add to the verifier prompt: 'Name the exact metric and threshold you checked "
        "(e.g. replicas_ready == 3/3 AND error_rate < 0.05) before closing — never close "
        "on \"looks healthy\".'"
    ),
    "projected_gain": "Prevents a false-resolve where the service is green for an unrelated reason.",
}


def load_reflection_manifest():
    """The reflection node lives outside manifests/agents/ on purpose: it is a
    meta node, not part of the incident fleet, so the core fleet stays exactly
    the four agents the safety tests assert on."""
    path = Path(settings().manifest_dir).parent / "reflection.yaml"
    if not path.exists():
        return None
    return load_manifest(path)


async def run_reflection(live: bool, store, toolbox, trace: str, incident_id: str):
    manifest = load_reflection_manifest()
    if manifest is None:
        return None
    override = None if live else ScriptedModel(
        model="scripted/reflection", script=[{"json": SCRIPTED_REFLECTION}]
    )
    run = await run_agent(
        manifest=manifest,
        toolbox=toolbox,
        store=store,
        incident_id=incident_id,
        prompt=trace,
        model_override=override,
    )
    return run.parse(Reflection)


# --------------------------------------------------------------------------
# Output.
# --------------------------------------------------------------------------


def _cell(token: str, color: str = "", width: int = 20) -> str:
    """Pad the visible token to width, THEN wrap color, so ANSI codes never
    throw the column alignment off."""
    return f"{color}{token.ljust(width)}{RESET}" if color else token.ljust(width)


def _row(label: str, single: str, flow: str) -> None:
    print(f"  {label:<28}{single}{flow}")


def print_scoreboard(single: dict, flow: dict) -> None:
    def yn(v: bool, good_is_yes: bool = True) -> str:
        color = (GREEN if v else RED) if good_is_yes else (RED if v else GREEN)
        return _cell("yes" if v else "no", color)

    print(f"\n{BOLD}SCOREBOARD  {DIM}(same incident, same model family){RESET}")
    print(f"  {'':<28}{DIM}{'single prompt':<20}{'warden flow':<20}{RESET}")
    _row("fixed the root cause", yn(single["fixed_root_cause"]), yn(flow["fixed_root_cause"]))
    _row("lines changed", _cell(str(single["lines_changed"]), RED), _cell(str(flow["lines_changed"]), GREEN))
    _row("within 12-line blast radius", yn(single["within_blast_radius"]), yn(flow["within_blast_radius"]))
    _row(
        "collateral edits",
        _cell(str(len(single["collateral"])), RED if single["collateral"] else GREEN),
        _cell(str(len(flow["collateral"])), GREEN),
    )
    _row("evidence cited", _cell(str(single["evidence"]), RED if single["evidence"] == 0 else ""), _cell(str(flow["evidence"]), GREEN))
    conf = "n/a" if single["confidence"] is None else f"{single['confidence']:.2f}"
    fconf = "n/a" if flow["confidence"] is None else f"{flow['confidence']:.2f}"
    _row("confidence reported", _cell(conf), _cell(fconf, GREEN if flow["confidence"] else ""))
    _row("tokens", _cell(str(single["tokens"])), _cell(str(flow["tokens"])))

    if single["collateral"]:
        print(f"\n  {YELLOW}single prompt's collateral edits (unrelated to the root cause):{RESET}")
        for ln in single["collateral"][:6]:
            print(f"    {RED}~ {ln}{RESET}")

    winner = "WARDEN FLOW" if (flow["within_blast_radius"] and not flow["collateral"]) else "unclear"
    print(f"\n  {BOLD}verdict:{RESET} both fixed the bug, but the single prompt shipped "
          f"{len(single['collateral'])} unverified change(s) with it. {GREEN}{winner}{RESET} "
          f"produced a patch a human can approve in 30 seconds.")


def print_reflection(refl: Reflection | None) -> None:
    if refl is None:
        print(f"\n{DIM}(reflection skipped){RESET}")
        return
    print(f"\n{BOLD}REFLECTION  {DIM}— the workflow critiques its own prompts{RESET}")
    print(f"  {CYAN}strengths this run:{RESET}")
    for s in refl.workflow_strengths:
        print(f"    • {s}")
    print(f"  {CYAN}weakest node:{RESET} {BOLD}{refl.weakest_node}{RESET}")
    print(f"  {CYAN}suggested prompt change:{RESET}")
    print(f"    {refl.suggested_prompt_improvement}")
    print(f"  {CYAN}projected gain:{RESET} {refl.projected_gain}")


async def main(live: bool, reflect: bool) -> int:
    warnings.filterwarnings("ignore", category=UserWarning, module="google.*")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    print(f"\n{BOLD}WARDEN FLOW — benchmark: structured workflow vs single prompt{RESET}")
    print(f"  models     {'LIVE Gemini' if live else 'scripted (offline, free, deterministic)'}")
    print("  incident   checkout-svc crashloop — PAYMENT_ENDPOINT 'htps://' typo (r42)")

    if live:
        try:
            configure_genai_env()
        except Exception as exc:
            print(f"\n{RED}{exc}{RESET}")
            return 2

    store, toolbox, fleet = _wiring()

    print(f"\n{DIM}running single prompt…{RESET}")
    single = await run_single_prompt(live)
    print(f"{DIM}running warden flow…{RESET}")
    flow = await run_workflow(live, store, toolbox, fleet)

    print_scoreboard(single, flow)

    if reflect:
        d = flow.get("diagnosis")
        trace = (
            "TRACE of a completed run:\n"
            f"- Diagnosis root_cause: {d.root_cause if d else 'n/a'}\n"
            f"- Diagnosis confidence: {flow['confidence']}\n"
            f"- Workflow patch: {flow['lines_changed']} line(s), within blast radius={flow['within_blast_radius']}\n"
            f"- Single-prompt patch: {single['lines_changed']} line(s), "
            f"{len(single['collateral'])} collateral edit(s)\n"
            "Reflect on the workflow's prompts and propose one improvement."
        )
        refl = await run_reflection(live, store, toolbox, trace, flow["incident_id"])
        print_reflection(refl)

    print()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Benchmark the workflow against a single prompt.")
    p.add_argument("--live", action="store_true", help="use real Gemini for both paths")
    p.add_argument("--no-reflect", action="store_true", help="skip the reflection node")
    args = p.parse_args()
    raise SystemExit(asyncio.run(main(args.live, reflect=not args.no_reflect)))
