"""The DELIVER pipeline: a repo in, reviewed artifacts out.

Same shape as the incident orchestrator — explicit, inspectable handoffs, each
node governed and audited — but pointed at shipping a service rather than fixing
one:

    Assess -> Containerize -> Pipeline -> Deploy-Plan -> [Human review] -> Verify

Each node returns a typed object and hands its structure to the next, so the
pipeline generator reasons over the real Dockerfile and the verifier reasons over
everything that was generated — never over the raw repo re-read from scratch.
"""

from __future__ import annotations

import logging
import uuid

from warden.agents.runtime import AgentRun, run_agent
from warden.control_plane.store import Store
from warden.delivery.targets import deploy_hint as _deploy_hint
from warden.delivery.targets import deploy_summary as _deploy_summary
from warden.llm import deliver_model_override
from warden.models import (
    AgentManifest,
    DeployPlan,
    Dockerfile,
    Pipeline,
    RepoProfile,
)
from warden.tools.toolbox import ToolBox

log = logging.getLogger("warden.delivery")


class DeliveryResult:
    def __init__(self, delivery_id: str, target: str) -> None:
        self.id = delivery_id
        self.target = target
        self.assess: AgentRun | None = None
        self.containerize: AgentRun | None = None
        self.pipeline: AgentRun | None = None
        self.deploy_plan: AgentRun | None = None
        self.verify: AgentRun | None = None
        self.stopped_at: str = ""

    @property
    def runs(self) -> list[AgentRun]:
        ordered = (self.assess, self.containerize, self.pipeline, self.deploy_plan, self.verify)
        return [r for r in ordered if r]

    @property
    def total_tokens(self) -> int:
        return sum(r.run.total_tokens for r in self.runs)


async def deliver(
    *,
    target: str,
    fleet: dict[str, AgentManifest],
    toolbox: ToolBox,
    store: Store,
    models: dict | None = None,
) -> DeliveryResult:
    """Run one service through the delivery workflow.

    `models` maps node name -> a scripted model (offline). When None, live
    models are used, optionally overridden globally by DELIVER_MODEL
    (Azure/OpenAI/Anthropic via LiteLlm).
    """
    models = models or {}
    override = deliver_model_override() if not models else None

    def pick(name: str):
        return models.get(name) if models else override

    async def node(name: str, prompt: str) -> AgentRun:
        return await run_agent(
            manifest=fleet[name],
            toolbox=toolbox,
            store=store,
            incident_id=delivery_id,
            prompt=prompt,
            model_override=pick(name),
        )

    delivery_id = f"DEL-{uuid.uuid4().hex[:8].upper()}"
    toolbox.bind_incident(delivery_id)
    result = DeliveryResult(delivery_id, target)
    log.info("delivery %s — target %s", delivery_id, target)

    # -- 1. Assess ---------------------------------------------------------
    result.assess = await node(
        "assess",
        f"Assess the service at '{target}' so it can be containerized and "
        "deployed. Read the dependency manifest and entrypoint before answering.",
    )
    profile = result.assess.parse(RepoProfile)
    if profile is None:
        result.stopped_at = "assess"
        return result

    profile_block = (
        f"Language: {profile.language}\nFramework: {profile.framework}\n"
        f"Entrypoint: {profile.entrypoint}\nPorts: {profile.ports}\n"
        f"Build system: {profile.build_system}\n"
        f"Dependencies: {', '.join(profile.dependencies) or 'stdlib only'}\n"
        f"Notes: {profile.notes}"
    )

    # -- 2. Containerize ---------------------------------------------------
    result.containerize = await node(
        "containerize",
        "Write a production Dockerfile for this service.\n" + profile_block
        + "\n\nEnforce: pinned base, multi-stage, non-root, no baked secrets.",
    )
    dockerfile = result.containerize.parse(Dockerfile)
    if dockerfile is None:
        result.stopped_at = "containerize"
        return result

    # -- 3. Pipeline (handoff: profile + the chosen base image) ------------
    result.pipeline = await node(
        "pipeline",
        "Write a CI/CD pipeline for this containerized service.\n" + profile_block
        + f"\nBase image: {dockerfile.base_image}\n\n"
        "Stages: build, test, scan, push (main only), deploy. Reference secrets, "
        "do not hardcode them; use least-privilege permissions.\n\n" + _deploy_hint(),
    )
    pipeline = result.pipeline.parse(Pipeline)

    # -- 4. Deploy plan (handoff: profile + dockerfile) --------------------
    result.deploy_plan = await node(
        "deploy_plan",
        "Write the Kubernetes manifests and rollout plan for this service.\n"
        + profile_block
        + f"\nContainer runs as non-root, listens on {profile.ports}. "
        "Set resource requests/limits, liveness/readiness probes, a non-root "
        "securityContext, and an immutable image tag. State the rollback in one line.\n\n"
        + _deploy_summary(),
    )
    deploy_plan = result.deploy_plan.parse(DeployPlan)

    # -- 5. Verify (handoff: everything generated) — the gate before review
    manifests_text = "\n".join(
        f"# {m.path}\n{m.content}" for m in (deploy_plan.manifests if deploy_plan else [])
    )
    result.verify = await node(
        "verify_artifacts",
        "Validate the generated delivery artifacts. Report pass/issues.\n"
        + _deploy_summary() + "\n\n"
        f"--- Dockerfile ---\n{dockerfile.content}\n\n"
        f"--- Pipeline ---\n{pipeline.content if pipeline else '(none)'}\n\n"
        f"--- Manifests ---\n{manifests_text or '(none)'}",
    )

    log.info("delivery %s complete — artifacts ready for human review", delivery_id)
    return result


# --------------------------------------------------------------------------
# Streaming variant — yields an event per stage so the UI can show the work as
# it happens (cloning, then each node active, then its real output).
# --------------------------------------------------------------------------

_NODE_ORDER = [
    ("assess", RepoProfile, "Reading your repo — language, entrypoint, ports."),
    ("containerize", Dockerfile, "Writing a production Dockerfile."),
    ("pipeline", Pipeline, "Writing the CI/CD pipeline."),
    ("deploy_plan", DeployPlan, "Writing the Kubernetes manifests and rollout."),
    ("verify_artifacts", None, "Validating every artifact before review."),
]


async def deliver_events(
    *, target, fleet, store, github, estate, models=None, do_pr=False
):
    """Async generator yielding {stage, status, ...} events through the workflow."""
    import asyncio
    import os

    from warden.delivery.source import is_remote, resolve_source

    models = models or {}
    override = deliver_model_override() if not models else None

    def pick(name):
        return models.get(name) if models else override

    delivery_id = f"DEL-{uuid.uuid4().hex[:8].upper()}"

    # -- clone / locate the source ----------------------------------------
    yield {"stage": "clone", "status": "start", "target": target,
           "remote": is_remote(target)}
    try:
        source_dir = await asyncio.to_thread(resolve_source, target)
    except Exception as exc:
        yield {"stage": "clone", "status": "error", "error": str(exc)[:200]}
        return
    files = []
    for root, _dirs, fnames in os.walk(source_dir):
        if any(p in root for p in (".git", "node_modules", ".venv")):
            continue
        for f in fnames:
            files.append(os.path.relpath(os.path.join(root, f), source_dir))
        if len(files) > 40:
            break
    yield {"stage": "clone", "status": "done", "fileCount": len(files),
           "files": sorted(files)[:16]}

    toolbox = ToolBox(estate=estate, store=store, github=github, source_root=source_dir)
    toolbox.bind_incident(delivery_id)

    prompts = {
        "assess": (
            f"Assess the service at '{target}' so it can be containerized and deployed. "
            "Read the dependency manifest and entrypoint before answering."
        ),
    }
    parsed = {}
    total_tokens = 0

    async def run_one(name, prompt):
        return await run_agent(manifest=fleet[name], toolbox=toolbox, store=store,
                               incident_id=delivery_id, prompt=prompt, model_override=pick(name))

    for name, schema, thinking in _NODE_ORDER:
        # Build the prompt with the handoff from earlier nodes.
        if name == "assess":
            prompt = prompts["assess"]
        else:
            profile = parsed.get("assess")
            pblock = ""
            if profile:
                pblock = (
                    f"Language: {profile.language}\nFramework: {profile.framework}\n"
                    f"Entrypoint: {profile.entrypoint}\nPorts: {profile.ports}\n"
                    f"Build system: {profile.build_system}\n"
                    f"Dependencies: {', '.join(profile.dependencies) or 'stdlib only'}\n"
                    f"Notes: {profile.notes}"
                )
            if name == "containerize":
                prompt = ("Write a production Dockerfile for this service.\n" + pblock
                          + "\n\nEnforce: pinned base, multi-stage, non-root, no baked secrets.")
            elif name == "pipeline":
                df = parsed.get("containerize")
                prompt = ("Write a CI/CD pipeline for this containerized service.\n" + pblock
                          + f"\nBase image: {df.base_image if df else 'the generated image'}\n\n"
                          "Stages: build, test, scan, push (main only), deploy. Reference secrets, "
                          "do not hardcode; least-privilege permissions.\n\n" + _deploy_hint())
            elif name == "deploy_plan":
                prompt = ("Write the Kubernetes manifests and rollout plan for this service.\n"
                          + pblock + "\nSet resource requests/limits, liveness/readiness probes, a "
                          "non-root securityContext and an immutable image tag. State the rollback "
                          "in one line.\n\n" + _deploy_summary())
            else:  # verify_artifacts
                df = parsed.get("containerize")
                pl = parsed.get("pipeline")
                dp = parsed.get("deploy_plan")
                mtext = "\n".join(f"# {m.path}\n{m.content}" for m in (dp.manifests if dp else []))
                prompt = ("Validate the generated delivery artifacts. Report pass/issues.\n"
                          + _deploy_summary() + "\n\n"
                          f"--- Dockerfile ---\n{df.content if df else '(none)'}\n\n"
                          f"--- Pipeline ---\n{pl.content if pl else '(none)'}\n\n"
                          f"--- Manifests ---\n{mtext or '(none)'}")

        yield {"stage": name, "status": "start", "thinking": thinking}
        try:
            run = await run_one(name, prompt)
        except Exception as exc:
            yield {"stage": name, "status": "error", "error": str(exc)[:300]}
            return
        if schema is not None:
            obj = run.parse(schema)
            if obj is not None:
                parsed[name] = obj
        total_tokens += run.run.total_tokens
        yield {"stage": name, "status": "done", "model": run.run.model,
               "tokens": run.run.total_tokens, "output": run.structured or {}}

    # -- pull request ------------------------------------------------------
    pr_info = None
    if do_pr:
        yield {"stage": "pr", "status": "start", "thinking": "Opening a pull request on your repo."}
        from warden.delivery.publish import open_delivery_pr

        df, pl, dp = parsed.get("containerize"), parsed.get("pipeline"), parsed.get("deploy_plan")
        if df:
            pr_info = await open_delivery_pr(
                target=target, dockerfile=df.content,
                pipeline=pl.content if pl else "",
                manifests=dp.as_dict() if dp else {},
            )
        yield {"stage": "pr", "status": "done", "pr": pr_info}

    yield {"stage": "complete", "status": "done", "id": delivery_id,
           "totalTokens": total_tokens, "pr": pr_info}
