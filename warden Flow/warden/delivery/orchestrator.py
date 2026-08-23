"""The DELIVER pipeline: a repo in, reviewed artifacts out.

Same shape as the incident orchestrator — explicit, inspectable handoffs, each
node governed and audited — but pointed at shipping a service rather than fixing
one. Step 1 covers Assess -> Containerize; Pipeline, Deploy-Plan and Verify are
added the same way.
"""

from __future__ import annotations

import logging
import uuid

from warden.agents.runtime import AgentRun, run_agent
from warden.control_plane.store import Store
from warden.llm import deliver_model_override
from warden.models import AgentManifest, Dockerfile, RepoProfile
from warden.tools.toolbox import ToolBox

log = logging.getLogger("warden.delivery")


class DeliveryResult:
    def __init__(self, delivery_id: str, target: str) -> None:
        self.id = delivery_id
        self.target = target
        self.assess: AgentRun | None = None
        self.containerize: AgentRun | None = None
        self.stopped_at: str = ""

    @property
    def runs(self) -> list[AgentRun]:
        return [r for r in (self.assess, self.containerize) if r]

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

    delivery_id = f"DEL-{uuid.uuid4().hex[:8].upper()}"
    toolbox.bind_incident(delivery_id)
    result = DeliveryResult(delivery_id, target)
    log.info("delivery %s — target %s", delivery_id, target)

    # -- 1. Assess ---------------------------------------------------------
    result.assess = await run_agent(
        manifest=fleet["assess"],
        toolbox=toolbox,
        store=store,
        incident_id=delivery_id,
        prompt=(
            f"Assess the service at '{target}' so it can be containerized and "
            "deployed. Read the dependency manifest and entrypoint before answering."
        ),
        model_override=pick("assess"),
    )
    profile = result.assess.parse(RepoProfile)
    if profile is None:
        result.stopped_at = "assess"
        log.warning("%s: assess produced no structured profile", delivery_id)
        return result

    # -- 2. Containerize (structured handoff of the profile) ---------------
    result.containerize = await run_agent(
        manifest=fleet["containerize"],
        toolbox=toolbox,
        store=store,
        incident_id=delivery_id,
        prompt=(
            "Write a production Dockerfile for this service.\n"
            f"Language: {profile.language}\n"
            f"Framework: {profile.framework}\n"
            f"Entrypoint: {profile.entrypoint}\n"
            f"Ports: {profile.ports}\n"
            f"Build system: {profile.build_system}\n"
            f"Dependencies: {', '.join(profile.dependencies) or 'stdlib only'}\n"
            f"Notes: {profile.notes}\n\n"
            "Enforce: pinned base, multi-stage, non-root, no baked secrets."
        ),
        model_override=pick("containerize"),
    )
    if result.containerize.parse(Dockerfile) is None:
        result.stopped_at = "containerize"
        log.warning("%s: containerize produced no structured Dockerfile", delivery_id)

    return result
