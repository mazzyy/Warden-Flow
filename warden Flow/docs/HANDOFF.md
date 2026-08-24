# Warden Flow — Project Handoff & Status

_Last updated: 2026-08-24. This document is written so a new session (human or LLM) can pick the project up cold: what it is, what works, exactly where we are, and the open problems we are actively fighting._

---

## 1. What this project is

**Warden Flow is an AI DevOps engineer.** You give it an application repository (local path or GitHub URL). It reads the code and produces production-ready delivery artifacts — a Dockerfile, a CI/CD pipeline, Kubernetes/deploy manifests — validates them, and hands them back for human review as a **pull request**. With explicit approval it can also execute build → push → deploy.

It is built for **Reverie Hacks 2026 (ML Prompt Engineering track)**.

### Why it is a *different* project from "Warden"

The original **Warden** (built for a Google hackathon) is a **governed fleet of autonomous SRE agents** that responds to incidents on a running system: it triages an alert, diagnoses root cause, proposes a small GitOps fix, and verifies it — all reactive, all after something breaks.

Warden Flow keeps that reactive capability but adds a **proactive** direction: instead of only *fixing* running systems, it *ships* new ones. The headline workflow (DELIVER) turns a plain repo into deployable infrastructure before any incident exists. So the project now has **two workflows that share one governance spine**:

| Workflow | Direction | Trigger | Nodes | Output |
| --- | --- | --- | --- | --- |
| **DELIVER** (new — the Reverie headline) | Proactive: ship a service | A repo | Assess → Containerize → Pipeline → Deploy-plan → Verify | Dockerfile + CI + manifests, as a PR |
| **OPERATE** (original Warden) | Reactive: fix a running service | An incident/alert | Triage → Diagnose → Remediate → Verify | A small GitOps patch, as a PR |

Both use the same design: **typed, inspectable handoffs between single-purpose nodes**, policy + budget + audit governance, and a **human-in-the-loop boundary (the PR)** — the agent's only write primitive is opening a PR; a human reviews and merges.

**The submission must keep OPERATE working**, not just DELIVER. It is the proof that the governance/agent core is real and general.

---

## 2. Architecture (both workflows)

- **Multi-node LLM workflow.** Each node is a small agent with one job. It returns a **typed structured output** (Pydantic schema, enforced by the runtime) and hands that structure to the next node. No single mega-prompt makes every decision.
- **Runtime:** Google ADK (`LlmAgent`, `run_agent`). Non-Gemini models routed through **LiteLLM**.
- **Model in use:** **Azure GPT-5.6** (`DELIVER_MODEL=azure/gpt-5.6-sol`) via LiteLLM's `azure/` provider. (Gemini/Vertex still supported; Azure is what the live demo runs on — Reverie has no model/cloud restriction and we have Azure credits.)
- **Governance / control plane:** policy matrix, budget guard (`BUDGET_USD_CAP`), audit store. Tools are scoped (e.g. `source:local:read`).
- **Human boundary:** PR only. `--apply` (execute deploy) is separate and explicit.
- **Dashboard:** a live "studio" UI streams the workflow over SSE — clone → each node active → the real artifact each node produced — so the work is visible in a demo video.

### Key paths in the repo (`warden Flow/`)
```
warden/delivery/        DELIVER orchestration, source clone, PR publish, apply plan, deploy targets
warden/agents/          node prompts (definitions.py) + ADK runtime; OPERATE incident agents
warden/control_plane/   policy, budgets, manifests, audit store
warden/tools/           scoped repo/source/infra tool surface + github_client
warden/dashboard/       FastAPI api.py + studio.html (live SSE UI)
manifests/agents/       4 OPERATE agents: triage, diagnostician, remediator, verifier
manifests/delivery/     5 DELIVER nodes: assess, containerize, pipeline, deploy_plan, verify
manifests/reflection.yaml  meta/reflection node
docs/reverie/           flowchart, workflow-vs-single-prompt, node docs, Devpost material
examples/checkout-svc/  bundled sample service for offline runs
```

---

## 3. Environment & how to run (this matters — read before running)

- **The code lives and runs on the user's Mac**, at `…/Warden Flow/warden Flow`. Live model + Azure calls **must run on the Mac** — the cloud assistant sandbox has Azure/egress blocked, so it cannot do live runs.
- **`.env`** holds all creds. Important keys:
  - `DELIVER_MODEL=azure/gpt-5.6-sol`, `AZURE_API_KEY`, `AZURE_API_BASE=https://musawarsoomro-6354-resource.openai.azure.com/`, `AZURE_API_VERSION=2024-12-01-preview`
  - `DEPLOY_TARGET=containerapp`
  - `GITHUB_TOKEN=...` (a fine-grained PAT). **Note:** the DELIVER PR is actually opened via a **GitHub App** (`GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, key at `~/.warden/github-app.pem`), not the PAT.
  - `WARDEN_USE_FIXTURES=false` for live.
- **Dashboard (the demo path):**
  ```bash
  source .venv/bin/activate
  warden-dashboard          # → http://localhost:8000/studio
  ```
  Enter a repo URL, toggle "Open a PR", run live. Restart it after any code edit (Python won't hot-reload prompt changes).
- **CLI:**
  ```bash
  python -m warden.deliver --target <path-or-URL>          # generate + report only
  python -m warden.deliver --target <URL> --pr             # open a PR
  python -m warden.deliver --target <path> --apply         # build→push→deploy (explicit)
  ```
- **OPERATE demo (offline, deterministic):** `make demo`
- **Benchmark (structured vs single prompt):** `make bench-deliver`

---

## 4. Live target & Azure infrastructure (already provisioned)

- **Repo under delivery:** `github.com/mazzyy/testing-python`
  - Default branch is **`master`** (not `main`). It's actually a **Node/Vite frontend** despite the name (the agent assessed it as such: `node:20` build, `nginx-unprivileged` runtime).
- **Azure (all created and working):**
  - Resource group: `warden-rg`
  - ACR: `mazzyacr2026` (login server `mazzyacr2026.azurecr.io`)
  - Container App: `testing-python`
  - Service principal: `warden-ci` (clientId `5943100b-8226-4776-98d6-d7517cef21aa`), has **AcrPush**.
- **Full reproducible Azure runbook (so you never rebuild it): [`docs/deploy-azure.md`](deploy-azure.md)** — resources, exact `az` commands, GitHub secret/variable mapping, and a verify step. Note it flags that the SP likely still needs a **Contributor** role on `warden-rg` for `az containerapp update` to succeed.
- **GitHub Actions config on `testing-python`:**
  - Secret: `AZURE_CREDENTIALS` = the full service-principal JSON (`az ad sp create-for-rbac --sdk-auth` output).
  - Variables: `ACR_NAME=mazzyacr2026`, `ACR_LOGIN_SERVER=mazzyacr2026.azurecr.io`, `IMAGE_NAME=testing-python`, `CONTAINERAPP_NAME=testing-python`, `AZURE_RESOURCE_GROUP=warden-rg`.

---

## 5. Exactly where we are right now

- **PR #3 is open** on `mazzyy/testing-python` (`warden/add-devops--…` branch). The agent generated `Dockerfile`, `.github/workflows/deliver.yml`, and `k8s/` manifests **on Azure GPT-5.6**. The **Verify node passed** (target-aware — it correctly treats the k8s manifests as reference-only for a Container Apps target).
- We are getting the pipeline **green so it actually deploys**. The generated `deliver.yml` had three real bugs (see §6). They have been **patched by hand directly on the PR branch via the GitHub web editor** (the assistant cannot push — see §6.4).
- **Immediate next action:** confirm the scan job goes green with the Docker-based Trivy step → **merge into `master`** → the `push` + `deploy` jobs (gated on the default branch) fire → Container App `testing-python` updates to the exact commit image. Watch the Actions run to confirm the deploy succeeds.

---

## 6. The problems we are facing (the important part)

### 6.1 Core problem: the agent generated a CI pipeline a human had to fix

This is the central weakness to solve. The DELIVER agent produced a plausible, well-structured pipeline that **did not actually run green**. A human (the assistant, reviewing the Actions logs) had to diagnose and patch three things:

1. **Wrong deploy gate.** The pipeline hardcoded `if: github.ref == 'refs/heads/main'` for the push/deploy jobs, but the repo's default branch is **`master`**. Result: after merge, push + deploy would silently **skip forever** — nothing deploys. (The agent *did* correctly detect `master` when opening the PR against it, but still wrote `main` into the pipeline.)
2. **Non-existent action tag.** It referenced `aquasecurity/trivy-action@0.33.1`; the real tag is **`v0.33.1`** (v-prefixed). GitHub can't resolve `@0.33.1` → scan job dies in ~2s.
3. **Flaky install action.** Even at the right tag, `aquasecurity/setup-trivy` downloads the Trivy binary from GitHub's API and **rate-limits on shared runners** → install exits 1. Fixed by running Trivy from its official container image (`aquasec/trivy:0.65.0`) instead.

**The user's point stands:** the agent should have handled this itself. A human editing CI by hand defeats the "AI DevOps engineer" premise. Closing this gap is the top engineering priority.

### 6.2 Two levels of fix (design direction)

- **Level 1 — generator guardrails (cheap, deterministic-ish).** Tighten the Pipeline node prompt so it:
  - gates push/deploy on the **actual default branch** — emit `if: github.event_name == 'push' && github.ref_name == github.event.repository.default_branch` instead of hardcoding `main`;
  - pins third-party actions to **tags that exist** (note trivy-action tags are v-prefixed), or prefers running scanners **via their container image** to avoid install/rate-limit flakiness.
- **Level 2 — a real closed loop (the compelling version).** Add a node/loop that **reads the GitHub Actions run result** for the PR and iterates the artifacts until the pipeline is green — i.e. the agent verifies its own CI *by running it*, not just by static validation. This turns "plausible YAML" into "proven-green YAML" and is the strongest answer to 6.1. The existing **reflection** node (`manifests/reflection.yaml`) is the natural place to grow this.

**Status of these fixes:** The Verify node and Deploy-plan node were made **target-aware** (done — `deploy_summary()` in `warden/delivery/targets.py`, injected into both prompts; Container Apps k8s manifests now correctly treated as reference-only). **The `main`→default-branch and Trivy guardrails in the generator prompts are NOT done yet** — `warden/agents/definitions.py` (lines ~205, 262) and `warden/delivery/orchestrator.py` (the two `"push (main only)"` prompt strings) still say `main`. So a fresh live run will **regenerate the same bugs** until these are patched. Patch them next.

### 6.3 Current gate mechanism knows nothing about the real run

Verify passes on *static* checks (pinned base, non-root, scan stage present, secrets referenced, probes, etc.). It cannot catch "this action tag doesn't exist" or "this gate branch is wrong" because it never runs the pipeline. That is why 6.1 slipped through. Level-2 above is the fix.

### 6.4 Assistant can't push to the target repo (workflow note, not a project bug)

- The cloud sandbox's git proxy blocks pushing to `mazzyy/testing-python` (not in its authorized set).
- From the device VM, the **PAT is read-only** for that repo (clone works, push denied), and the **GitHub App key lives on the Mac host (`~/.warden/…pem`), which isn't mounted** into the VM.
- So CI fixes were applied by the **user pasting the corrected file in the GitHub web editor**. Reliable, but manual. (A tiny find/replace mangled the action name once — full-file paste is safer than surgical edits.)

### 6.5 Secret hygiene

Live secrets (Azure API key, GitHub PATs, AKS reader token, webhook secret) were pasted into chat during setup. **Rotate them all after the hackathon**: regenerate the Azure key, revoke the PATs, reset the AKS token, and reset the SP credential (`az ad sp credential reset --id 5943100b-8226-4776-98d6-d7517cef21aa`).

---

## 7. Next steps (ordered)

1. **Land the deploy.** Scan green on PR #3 → merge to `master` → watch push + deploy jobs → confirm Container App `testing-python` serves the new image. This proves the end-to-end loop.
2. **Fix the generators (§6.2 Level 1).** Patch `definitions.py` + `orchestrator.py` so re-runs emit a default-branch gate and resolvable/containerized Trivy. Re-run live once to confirm a **fresh PR is green without hand-edits**.
3. **(Stretch) Close the loop (§6.2 Level 2).** Grow the reflection node into a "read Actions result → repair artifacts → re-push" cycle so the agent proves its own CI.
4. **Verify OPERATE still works.** Run `make demo`; keep the incident workflow in the submission and the video.
5. **Finalize Reverie deliverables.** `docs/reverie/`: flowchart PNG, workflow-vs-single-prompt writeup, node documentation, Devpost text — make sure they describe *both* workflows and the governance story.
6. **Rotate secrets (§6.5).**

---

## 8. One-paragraph summary for a brand-new session

Warden Flow is an AI DevOps engineer with two governed, multi-node LLM workflows sharing one spine: **DELIVER** (proactive — turn a repo into a Dockerfile + CI + deploy manifests, opened as a PR) and **OPERATE** (the original Warden — reactive incident triage → diagnose → remediate → verify as a GitOps PR). It runs on Azure GPT-5.6 via LiteLLM on the user's Mac; the human boundary is always a PR. Right now we're landing the first real deploy: the agent generated a full pipeline for `github.com/mazzyy/testing-python` (PR #3, Verify passed) targeting Azure Container Apps, but the generated `deliver.yml` had three bugs — a `main`-vs-`master` deploy gate, a bad Trivy action tag, and a rate-limiting Trivy install — which a human patched by hand on the PR. The **central open problem** is exactly that: the agent should produce runnable CI itself. The fix is generator guardrails (default-branch gate, resolvable/containerized scanners) and, ideally, a reflection loop that reads the Actions result and repairs until green. Azure infra and GitHub secrets/variables are all provisioned; the immediate task is scan-green → merge → confirm deploy, then patch the generators so the next run is clean.
