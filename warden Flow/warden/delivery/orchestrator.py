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
        "do not hardcode them; use least-privilege permissions.",
    )
    pipeline = result.pipeline.parse(Pipeline)

    # -- 4. Deploy plan (handoff: profile + dockerfile) --------------------
    result.deploy_plan = await node(
        "deploy_plan",
        "Write the Kubernetes manifests and rollout plan for this service.\n"
        + profile_block
        + f"\nContainer runs as non-root, listens on {profile.ports}. "
        "Set resource requests/limits, liveness/readiness probes, a non-root "
        "securityContext, and an immutable image tag. State the rollback in one line.",
    )
    deploy_plan = result.deploy_plan.parse(DeployPlan)

    # -- 5. Verify (handoff: everything generated) — the gate before review
    manifests_text = "\n".join(
        f"# {m.path}\n{m.content}" for m in (deploy_plan.manifests if deploy_plan else [])
    )
    result.verify = await node(
        "verify_artifacts",
        "Validate the generated delivery artifacts. Report pass/issues.\n\n"
        f"--- Dockerfile ---\n{dockerfile.content}\n\n"
        f"--- Pipeline ---\n{pipeline.content if pipeline else '(none)'}\n\n"
        f"--- Manifests ---\n{manifests_text or '(none)'}",
    )

    log.info("delivery %s complete — artifacts ready for human review", delivery_id)
    return result
