# Warden Flow v2 — the AI DevOps Engineer

**The idea:** Warden Flow becomes an AI DevOps engineer with a full lifecycle — it **ships** your service (generate a Dockerfile, a pipeline, a deploy plan) *and* **operates** it (the incident workflow you already have). Same structured-prompting method, two workflows, one story. The delivery half is new and is what makes this a different project from Warden; the operate half is your existing engine, reused honestly as one capability of the whole.

One elegant thread ties it together: the service the DELIVER workflow containerizes and ships is the same `checkout-svc` app the OPERATE workflow later keeps healthy. One app, full lifecycle.

---

## Two workflows, one method

```
DELIVER (new, proactive)                          OPERATE (existing, reactive)
repo ─→ Assess ─→ Containerize ─→ Pipeline ─→      alert ─→ Triage ─→ Diagnose ─→
        Deploy-Plan ─→ [Human review] ─→ Verify    Remediate ─→ [Human review] ─→ Verify
                         │                                          │
                         └──────────→ running service ←────────────┘
```

Both are the same spine: narrow typed nodes, structured output per node, structured handoffs, a human gate on the only step that changes production. That consistency *is* the prompt-engineering thesis.

---

## The DELIVER workflow — nodes

| # | Node | LLM query | Structured output | Tools | Model / budget |
|---|------|-----------|-------------------|-------|----------------|
| 1 | **Assess** | What is this repo? language, framework, entrypoint, ports, deps | `RepoProfile` | list_repo_files, read_repo_file *(reused)* | flash · 60k |
| 2 | **Containerize** | Write a production Dockerfile for it | `Dockerfile` | read_repo_file | flash · 80k |
| 3 | **Pipeline** | Write a CI/CD pipeline: build→test→scan→push→deploy | `Pipeline` | — | flash · 80k |
| 4 | **Deploy Plan** | Write the deploy manifests + rollout/rollback strategy | `DeployPlan` | — | flash · 80k |
| 5 | **Human Review** | *(no LLM)* approve the generated artifacts as a PR | PR merge/reject | propose_patch *(reused)* | — |
| 6 | **Verify** | Validate the artifacts (lint/dry-run) without deploying | `VerifyReport` | — | flash · 40k |
| ✦ | **Apply** *(optional/stretch)* | Push to registry + deploy, given secrets | `ApplyResult` | new deploy tool | live only |

The prompt engineering lives in the constraints each node is *told* to enforce — non-root user, pinned base image, multi-stage build, no secrets baked in, resource limits, health probes, least-privilege pipeline. A single naive prompt skips all of them.

---

## New schemas (add to `warden/models.py`)

```python
class RepoProfile(BaseModel):
    language: str; framework: str; entrypoint: str
    ports: list[int]; build_system: str; dependencies: list[str]; notes: str

class Dockerfile(BaseModel):
    content: str; base_image: str; multistage: bool
    runs_as_nonroot: bool; rationale: str; security_notes: list[str]

class Pipeline(BaseModel):
    content: str; stages: list[str]; rationale: str

class DeployPlan(BaseModel):
    manifests: dict[str, str]      # path -> yaml
    strategy: str; rollback: str; rationale: str

class VerifyReport(BaseModel):
    checks: list[str]; passed: bool; issues: list[str]
```

---

## What we reuse vs. build

**Reuse unchanged (this is why it's fast and honest):**
- `warden/agents/runtime.py` — `run_agent`, budget ledger, audit, retries.
- The policy proxy, audit store, budget guards — every delivery node is governed identically.
- The manifest system + `output_schema` structured-output pattern.
- `read_repo_file` / `list_repo_files` / `propose_patch` tools in the toolbox.
- The `bench.py` pattern — clone it for a delivery benchmark.

**Build new:**
- Schemas above (models.py).
- Node prompts (a `delivery` section in definitions.py, or a new `warden/delivery/definitions.py`).
- Manifests under **`manifests/delivery/`** (a separate dir, so the incident fleet stays exactly 4 agents and the safety tests keep passing — same lesson as the reflection node).
- `warden/delivery/orchestrator.py` — sequences Assess → … → Verify, mirroring `agents/orchestrator.py`.
- `warden deliver` CLI (offline scripted + `--live`), plus `warden bench-deliver`.
- A sample input repo to deliver — reuse `estate-gitops/app/` (the checkout-svc source).

**Optional / stretch (kept off the critical path):**
- The **Apply** node + a deploy tool (push to Azure Container Registry, deploy to AKS/App Service).
- A dashboard "Deliver" lane.

---

## The killer comparison (the track-winner)

`warden bench-deliver` — same repo, two ways:

- **Single prompt:** "Here's my repo, write a Dockerfile and a CI pipeline." → typically returns: `FROM python:latest` (unpinned), **root user**, secrets echoed in the pipeline, no healthcheck, no resource limits, no image scan.
- **Warden Flow:** multi-stage, pinned base, **non-root**, secrets referenced not embedded, scan stage, probes, limits.

Score it automatically against a best-practice checklist (non-root? pinned base? multistage? no baked secrets? scan stage? probes? limits?), exactly like the incident bench scores diff lines. A vivid, computable "structured workflow beats single prompt" result — arguably stronger than the incident one, because insecure Dockerfiles are so visibly wrong.

---

## The new flowchart

Two lanes sharing the human-review gate and the "running service" node — DELIVER on top, OPERATE below — each node annotated with its LLM query, model, and structured output, and the two human-in-the-loop nodes highlighted. Replaces the single-lane flowchart in the Reverie deliverables.

---

## Build order

1. Schemas in models.py.
2. Delivery node prompts + `manifests/delivery/*.yaml`.
3. `warden/delivery/orchestrator.py` (reusing `run_agent`).
4. `warden deliver` CLI — get Assess → Containerize working end to end, offline scripted first.
5. Pipeline + Deploy-Plan nodes.
6. Verify node (dry-run validation: hadolint/yaml lint or structured checks).
7. `warden bench-deliver` — the comparison + auto-score.
8. New two-lane flowchart + update `docs/reverie/` docs.
9. **Optional:** Apply node → Azure (ACR + AKS/App Service).
10. **Optional:** dashboard Deliver lane.

Steps 1–8 are the whole differentiated, submittable project. 9–10 are stretch.

---

## Azure (optional, allowed by Reverie)

Reverie has no LLM/cloud restriction, so if you want:
- **Azure OpenAI** as the model — a config swap in the runtime (point the client at Azure). Not required; Gemini already works.
- **Azure Container Registry + AKS/App Service** as the deploy target for the optional Apply node — this is where your Azure credits fit naturally.

Keep these optional. None of them are needed to make it a different project or to win the prompt-engineering track — the generation-and-review workflow is.

---

## The one guardrail

The demonstrable core is **generate → review → verify (dry-run)**. Real `docker push` + deploy-with-secrets is the optional finale, never a dependency. Generation and review is what's different from Warden and what the track scores; live deploy is risky plumbing that adds no track points.
