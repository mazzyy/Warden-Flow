# Warden Flow

**Warden Flow is an AI DevOps engineer that turns an application repository into production-ready, reviewed delivery artifacts — so developers can stay focused on building the product.**

Give it a local repository or a GitHub URL. Warden Flow reads the application, generates the container, CI/CD workflow, and deployment configuration it needs, validates the result, and returns the work for human review as a pull request. With explicit approval it can also execute build → push → deploy.

```text
your application code
        ↓
assess → containerize → CI/CD → deploy plan → validate → human review (PR) → deploy
```

It also keeps the original Warden capability: an **incident-response** path that diagnoses a running workload and proposes a small GitOps fix. Both paths share the same guardrails, audit trail, budget limits, and human-approval boundary.

> Built for **Reverie Hacks 2026 (ML Prompt Engineering track)**. For full project status, current work, and open problems, see [`docs/HANDOFF.md`](docs/HANDOFF.md).

---

## Two workflows, one governed core

Warden Flow is a **multi-node LLM system**: each node has one job, returns a **typed structured output**, and hands that structure to the next node — no single mega-prompt makes every infrastructure decision. Every node is policy-governed, budget-limited, and audited, and the only write primitive is a pull request a human reviews.

| Workflow | Purpose | Nodes | Output |
| --- | --- | --- | --- |
| **DELIVER** | Proactively ship a service | Assess → Containerize → Pipeline → Deploy-plan → Validate | Dockerfile + CI/CD + manifests, as a PR |
| **OPERATE** | Reactively fix a running service | Triage → Diagnose → Remediate → Verify | A small GitOps patch, as a PR |

---

## What developers get (DELIVER)

For a supported service, Warden Flow produces:

- A production-minded `Dockerfile`: pinned base image, multi-stage build, non-root runtime, no baked-in secrets.
- A GitHub Actions workflow covering build, test, vulnerability scan, image push, and deployment.
- Kubernetes deploy manifests with resource limits, probes, a non-root security context, immutable image references, and a rollback plan.
- Deployment-aware CI for **Azure Container Apps**, **AKS**, or **Azure App Service**.
- A validation report describing what passed and what needs attention.

It reads your application to understand its language, dependencies, entrypoint, and ports. It does not rewrite your product code or silently apply infrastructure.

### How the DELIVER stages work

| Stage | Responsibility | Output |
| --- | --- | --- |
| Assess | Inspect codebase, dependencies, entrypoint, ports | `RepoProfile` |
| Containerize | Create a secure, production-ready Dockerfile | `Dockerfile` |
| Pipeline | Create build, test, scan, push, deploy automation | `Pipeline` |
| Deploy plan | Create manifests, rollout strategy, rollback guidance | `DeployPlan` |
| Validate | Check the generated artifacts before review | `VerifyReport` |

The Pipeline and Deploy-plan stages are **target-aware** via `DEPLOY_TARGET` (`containerapp` default, `aks`, `appservice`). For a non-Kubernetes target the generated k8s manifests are treated as reference-only, and Validate judges the image against how that target actually deploys.

---

## Quick start

From the `warden Flow` directory:

```bash
./setup.sh --deliver
```

Runs the delivery workflow against the bundled sample using scripted models — deterministic, free, no cloud account or API key.

Against your own service after setup:

```bash
.venv/bin/python -m warden.deliver --target /path/to/your-service                 # generate + report
.venv/bin/python -m warden.deliver --target https://github.com/org/service --pr   # open a reviewable PR
.venv/bin/python -m warden.deliver --target /path/to/your-service --apply         # build → push → deploy (explicit)
```

`--apply` is intentional and explicit: generation and validation never deploy by themselves.

### Live models

Offline commands use scripted models. For live generation, copy `.env.example` to `.env` and configure a provider. Gemini/Vertex are supported directly; Azure OpenAI, OpenAI, and Anthropic through LiteLLM. The current live demo runs on **Azure GPT-5.6**:

```bash
# .env
DELIVER_MODEL=azure/gpt-5.6-sol
AZURE_API_KEY=...
AZURE_API_BASE=https://<resource>.openai.azure.com/
AZURE_API_VERSION=2024-12-01-preview
DEPLOY_TARGET=containerapp
```

Then `make deliver-live`, or run the live dashboard:

```bash
make dashboard        # → http://localhost:8000/studio
```

The studio streams the workflow live — clone, then each node lighting up as it runs, with the real artifact each node produced.

---

## Current status (2026-08-24)

- DELIVER runs live on Azure GPT-5.6 and opens real PRs (via a GitHub App) with a Dockerfile, CI pipeline, and manifests.
- First end-to-end deploy in progress against `github.com/mazzyy/testing-python` → Azure Container Apps (ACR `mazzyacr2026`, Container App `testing-python`). Validate passes; the pipeline is being taken green so the deploy fires on merge to `master`.
- OPERATE (incident response) and the offline benchmark remain part of the submission.

## Known limitations & what we're improving

- **The agent's generated CI isn't always runnable yet.** In the first live deploy, the generated pipeline needed human fixes (a `main`-vs-`master` deploy gate, a mistyped Trivy action tag, and a rate-limiting Trivy install step). The Validate node checks artifacts *statically*, so it can't catch "this action tag doesn't exist" or "this branch gate is wrong."
- **Direction of fix:** (1) generator guardrails — gate on the repository's actual default branch and pin/scan via resolvable, container-based actions; (2) a reflection loop that reads the GitHub Actions run result and repairs the artifacts until the pipeline is green — so the agent proves its own CI by running it, not just validating it statically.

See [`docs/HANDOFF.md`](docs/HANDOFF.md) for the detailed status and the open-problem write-up.

---

## Safety and ownership

Warden Flow automates DevOps work without taking ownership from the engineering team.

- Developers own application code and review the generated operational artifacts.
- Generated artifacts are validated before handoff.
- A PR is the normal collaboration boundary; deployments require the explicit `--apply` action and valid credentials.
- The workflow is audited, policy-governed, and budget-limited; secrets are referenced through CI/CD secrets and environment config, never written into generated artifacts.

---

## OPERATE — the original Warden incident workflow

Warden began as a **governed fleet of autonomous SRE agents** for incident response, and that capability is fully part of Warden Flow. When something breaks on a running system, OPERATE:

1. **Triage** — classify the alert and scope the blast radius.
2. **Diagnose** — inspect the estate (read-only, scoped tools) and identify root cause.
3. **Remediate** — prepare a small, reviewable **GitOps patch** (a PR), never an unrestricted production write.
4. **Verify** — check the proposed fix against the observed failure before a human approves.

It uses the **same** typed-handoff, policy, budget, audit, and human-approval spine as DELIVER — which is the point: the governance core is general. Run it offline and deterministically:

```bash
make demo
```

---

## Common commands

| Command | Purpose |
| --- | --- |
| `./setup.sh --deliver` | Offline delivery workflow |
| `make deliver-live` | Delivery with a live model |
| `make dashboard` | Live studio dashboard |
| `make bench-deliver` | Staged delivery vs a single prompt, offline |
| `make demo` | Offline incident-response (OPERATE) workflow |
| `make test` | Test suite |
| `make probe` | Print the policy matrix |

## Repository layout

```text
warden/delivery/       DELIVER orchestration, source handling, PR publishing, apply plan, deploy targets
warden/agents/         node prompts + ADK runtime; OPERATE incident agents
warden/control_plane/  policy, budgets, manifests, audit store
warden/tools/          controlled repository, source, and infrastructure tool surface
warden/dashboard/      FastAPI api + live studio UI
manifests/agents/      OPERATE agents (triage, diagnostician, remediator, verifier)
manifests/delivery/    DELIVER nodes (assess, containerize, pipeline, deploy_plan, verify)
docs/reverie/          workflow details, benchmark material, submission docs
docs/HANDOFF.md        full status and open-problem write-up
```

## Why staged automation

`make bench-deliver` evaluates the staged workflow against a single broad prompt on the same service, scoring observable Dockerfile safeguards (pinned base, multi-stage, non-root, health check, no baked secrets) rather than a qualitative claim. That separation is the core design choice: developers supply the application expertise; Warden Flow handles the repeatable delivery engineering around it, with reviewable output and clear operational boundaries.
