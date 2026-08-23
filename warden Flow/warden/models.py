"""Domain types. These are the contract between every layer — keep them boring."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Estate — what the adapters return. Deliberately cloud-agnostic (ADR-005).
# --------------------------------------------------------------------------


class WorkloadRef(BaseModel):
    namespace: str
    name: str
    kind: Literal["Deployment", "Service", "CloudRunService"] = "Deployment"

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.kind.lower()}/{self.namespace}/{self.name}"


class Workload(BaseModel):
    ref: WorkloadRef
    replicas_desired: int = 0
    replicas_ready: int = 0
    # A rollout that cannot finish leaves ready == desired while updated lags,
    # because the previous ReplicaSet is still happily serving. Without these
    # two numbers that state is indistinguishable from perfect health.
    replicas_updated: int = 0
    replicas_available: int = 0
    image: str = ""


class ContainerState(BaseModel):
    name: str
    ready: bool
    restart_count: int = 0
    reason: str | None = None
    exit_code: int | None = None


class WorkloadDetail(BaseModel):
    ref: WorkloadRef
    replicas_desired: int = 0
    replicas_ready: int = 0
    # A rollout that cannot finish leaves ready == desired while updated lags,
    # because the previous ReplicaSet is still happily serving. Without these
    # two numbers that state is indistinguishable from perfect health.
    replicas_updated: int = 0
    replicas_available: int = 0
    image: str = ""
    # Without these an agent sees a bare base image, concludes the image is
    # misconfigured, and proposes replacing it — a live run did exactly that
    # and produced a pull request that would have broken the cluster.
    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    containers: list[ContainerState] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    conditions: list[str] = Field(default_factory=list)


class LogLine(BaseModel):
    ts: datetime
    container: str
    message: str


class Deploy(BaseModel):
    ts: datetime
    revision: str
    image: str
    changed_by: str = "unknown"
    commit_sha: str | None = None
    summary: str = ""


class MetricPoint(BaseModel):
    ts: datetime
    value: float


class MetricSeries(BaseModel):
    metric: str
    unit: str = ""
    points: list[MetricPoint] = Field(default_factory=list)


class Status(BaseModel):
    ref: WorkloadRef
    healthy: bool
    summary: str
    # Structured, so callers stop parsing `summary` to work out what happened.
    # `rollout` is the field that matters: a Deployment whose replicas are all
    # ready can still be in serious trouble if the revision that is ready is
    # the OLD one and the new one cannot start.
    rollout: str = "complete"  # complete | progressing | blocked | none
    reasons: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Agent manifests — the registry's source of truth (ADR-003)
# --------------------------------------------------------------------------


class BlastRadius(BaseModel):
    namespace: str = "demo"
    max_files_per_patch: int = Field(default=3, alias="maxFilesPerPatch")
    # A patch that rewrites half a file is not a remediation, whatever the
    # rationale says. Enforced at the write path, where the current contents
    # are available to diff against.
    max_changed_lines: int = Field(default=20, alias="maxChangedLines")
    model_config = {"populate_by_name": True}


class BudgetSpec(BaseModel):
    max_tokens_per_run: int = Field(default=120_000, alias="maxTokensPerRun")
    max_tool_calls: int = Field(default=25, alias="maxToolCalls")
    model_config = {"populate_by_name": True}


class CircuitBreakerSpec(BaseModel):
    failures_before_open: int = Field(default=3, alias="failuresBeforeOpen")
    cooldown_seconds: int = Field(default=900, alias="cooldownSeconds")
    model_config = {"populate_by_name": True}


class AgentSpec(BaseModel):
    model: str
    tools: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    blast_radius: BlastRadius = Field(default_factory=BlastRadius, alias="blastRadius")
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    approval: Literal["auto", "required"] = "auto"
    circuit_breaker: CircuitBreakerSpec = Field(
        default_factory=CircuitBreakerSpec, alias="circuitBreaker"
    )
    model_config = {"populate_by_name": True}


class AgentMetadata(BaseModel):
    name: str
    description: str = ""


class AgentManifest(BaseModel):
    api_version: str = Field(default="warden.dev/v1", alias="apiVersion")
    kind: Literal["Agent"] = "Agent"
    metadata: AgentMetadata
    spec: AgentSpec
    model_config = {"populate_by_name": True}

    @property
    def name(self) -> str:
        return self.metadata.name


# --------------------------------------------------------------------------
# Control plane records
# --------------------------------------------------------------------------


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    noise = "noise"


class IncidentStatus(StrEnum):
    open = "open"
    diagnosing = "diagnosing"
    remediating = "remediating"
    awaiting_merge = "awaiting_merge"
    verifying = "verifying"
    resolved = "resolved"
    abandoned = "abandoned"


class Incident(BaseModel):
    id: str
    source: str
    signature: str
    severity: Severity = Severity.medium
    status: IncidentStatus = IncidentStatus.open
    workload: WorkloadRef | None = None
    title: str = ""
    opened_at: datetime = Field(default_factory=utcnow)
    closed_at: datetime | None = None
    pr_url: str | None = None
    memory_refs: list[str] = Field(default_factory=list)


class RunStatus(StrEnum):
    running = "running"
    ok = "ok"
    failed = "failed"
    budget_exceeded = "budget_exceeded"
    killed = "killed"


class Run(BaseModel):
    id: str
    incident_id: str
    agent: str
    model: str
    status: RunStatus = RunStatus.running
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None
    # usage_metadata is emitted PER MODEL CALL, so a tool-using turn produces
    # several. These are running sums, never a last-value read.
    prompt_tokens: int = 0
    candidates_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    outcome: str = ""


class Decision(StrEnum):
    allow = "allow"
    deny = "deny"


class AuditRecord(BaseModel):
    id: str
    run_id: str
    incident_id: str
    agent: str
    tool: str
    args_redacted: dict[str, Any] = Field(default_factory=dict)
    decision: Decision
    reason: str = ""
    latency_ms: int = 0
    ts: datetime = Field(default_factory=utcnow)
    # What the tool actually returned, truncated and redacted. The audit log
    # recorded that a call was allowed but not what came back, which made it
    # impossible to check a diagnosis against its own evidence — the one thing
    # an audit trail for an agent most needs to support.
    result_preview: str = ""
    result_truncated: bool = False


class FleetState(BaseModel):
    kill_switch: bool = False
    drained_at: datetime | None = None
    note: str = ""


# --------------------------------------------------------------------------
# Agent outputs — used as ADK output_schema. NOTE: ADK stores output_key as a
# plain dict, not the pydantic instance, so re-hydrate with model_validate.
# --------------------------------------------------------------------------


class TriageVerdict(BaseModel):
    severity: Severity = Field(description="How serious this signal is")
    escalate: bool = Field(description="True if the fleet should investigate")
    duplicate_of: str | None = Field(
        default=None, description="Existing incident id if this is a repeat"
    )
    reasoning: str = Field(description="One or two sentences on why")


class Evidence(BaseModel):
    source: str = Field(description="Which tool produced this, e.g. get_workload_logs")
    detail: str = Field(description="The specific line, value or fact observed")


class Diagnosis(BaseModel):
    hypothesis: str = Field(description="What is wrong, in one sentence")
    root_cause: str = Field(description="The specific change or condition responsible")
    evidence: list[Evidence] = Field(description="Facts supporting the hypothesis")
    suggested_fix: str = Field(description="What change would resolve it")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1")


class ProposedPatch(BaseModel):
    pr_url: str | None = Field(default=None, description="URL of the opened pull request")
    files_changed: list[str] = Field(default_factory=list)
    rationale: str = Field(description="Why this patch fixes the incident")


class Reflection(BaseModel):
    """Output of the Reflection node — a prompt-engineering critique of a run.

    This is the feedback loop that makes Warden Flow a prompt-optimization
    workflow and not just an incident bot: after a run completes, an LLM reads
    the whole trace and proposes the single highest-leverage change to a node's
    prompt. It holds no tools and changes nothing — its product is a suggestion
    a human (or a future version of this workflow) can act on.
    """

    workflow_strengths: list[str] = Field(
        description="What the staged structure did well on this run"
    )
    weakest_node: str = Field(
        description="The one node whose prompt most limits reliability: triage|diagnostician|remediator|verifier"
    )
    suggested_prompt_improvement: str = Field(
        description="One concrete, specific change to that node's prompt — quote the wording to add"
    )
    projected_gain: str = Field(
        description="What failure this change would prevent, in one sentence"
    )


# --------------------------------------------------------------------------
# DELIVER workflow outputs — the proactive half. Same typed-node discipline as
# the incident (OPERATE) workflow, pointed at shipping a service instead of
# fixing one.
# --------------------------------------------------------------------------


class RepoProfile(BaseModel):
    """What the Assess node learns about a repository before shipping it."""

    language: str = Field(description="Primary language, e.g. python")
    framework: str = Field(description="Framework or 'none' if plain", default="none")
    entrypoint: str = Field(description="How the service starts, e.g. 'python -m app'")
    ports: list[int] = Field(default_factory=list, description="Ports the service listens on")
    build_system: str = Field(description="e.g. pip/requirements.txt, poetry, npm")
    dependencies: list[str] = Field(default_factory=list, description="Key runtime dependencies")
    notes: str = Field(default="", description="Anything a containerizer must know")


class Dockerfile(BaseModel):
    """The Containerize node's output — a production Dockerfile plus why."""

    content: str = Field(description="The full Dockerfile text")
    base_image: str = Field(description="The pinned base image chosen")
    multistage: bool = Field(description="True if a multi-stage build")
    runs_as_nonroot: bool = Field(description="True if the final stage drops to a non-root user")
    rationale: str = Field(description="Why this Dockerfile is shaped this way")
    security_notes: list[str] = Field(
        default_factory=list, description="Security decisions made, e.g. 'pinned base', 'non-root'"
    )


class Pipeline(BaseModel):
    """The Pipeline node's output — a CI/CD workflow."""

    content: str = Field(description="The full pipeline file (e.g. GitHub Actions YAML)")
    stages: list[str] = Field(description="Ordered stages, e.g. build, test, scan, push, deploy")
    rationale: str = Field(description="Why the pipeline is structured this way")


class DeployManifest(BaseModel):
    """One generated manifest file. A typed {path, content} pair rather than an
    open-ended dict, because Azure OpenAI's strict structured-output mode rejects
    objects with arbitrary keys."""

    path: str = Field(description="Repo-relative path, e.g. k8s/deployment.yaml")
    content: str = Field(description="The full manifest YAML")


class DeployPlan(BaseModel):
    """The Deploy-Plan node's output — manifests and a rollout strategy."""

    manifests: list[DeployManifest] = Field(
        default_factory=list, description="The manifests to write, each a path and its YAML"
    )
    strategy: str = Field(description="Rollout strategy, e.g. RollingUpdate maxSurge=1")
    rollback: str = Field(description="How a bad rollout is reversed")
    rationale: str = Field(description="Why this deployment shape")

    def as_dict(self) -> dict[str, str]:
        """path -> content, for the tools that write files."""
        return {m.path: m.content for m in self.manifests}


class VerifyReport(BaseModel):
    """The Verify node's output — did the generated artifacts pass validation."""

    checks: list[str] = Field(description="Checks that were run")
    passed: bool = Field(description="True if all critical checks passed")
    issues: list[str] = Field(default_factory=list, description="Problems found, if any")
