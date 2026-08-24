# Warden Flow

**An AI DevOps engineer.** Point it at a repository and it writes the container, the CI/CD pipeline and the deploy manifests, validates them, and hands them back as a pull request you review.

It also keeps the original **Warden**: a governed fleet of SRE agents that diagnoses a broken service and proposes a fix. Two workflows, one governance core.

Every node is a separate prompt returning a **typed object** the next node reads. No single mega-prompt makes every decision, and the only thing either fleet can write is a pull request.

> Built for **Reverie Hacks 2026 — ML Prompt Engineering**.

---

## Two workflows, one core

| | Direction | In | Out |
|---|---|---|---|
| **DELIVER** | proactive — ship a service | a repository | Dockerfile + CI/CD + manifests, as a PR |
| **OPERATE** | reactive — fix a running one | a production alert | a small GitOps patch, as a PR |

Both share the same spine: typed handoffs between single-purpose nodes, scoped tools, per-node budgets, an audit trail, and a human gate on the only step that writes anything.

---

## DELIVER — ship a service

![DELIVER workflow](docs/reverie/warden-flow-deliver.png)

Five nodes, each with one job. `assess` reads the code and reports what the service actually is. `containerize` writes a production Dockerfile from that profile. `pipeline` writes build → test → scan → push → deploy. `deploy_plan` writes the manifests and the rollback. `verify_artifacts` gates all three before a person sees them.

Target-aware via `DEPLOY_TARGET`: **Azure Container Apps** (default), **AKS**, or **App Service**.

```bash
./setup.sh --deliver                                              # offline, free, deterministic
.venv/bin/python -m warden.deliver --target /path/to/your-service # generate + report
.venv/bin/python -m warden.deliver --target <github-url> --pr     # open a reviewable PR
```

---

## OPERATE — fix a running service

![OPERATE workflow](docs/reverie/warden-operate.png)

Four nodes and a loop. `triage` decides whether the signal is real or noise. `diagnostician` reads the estate read-only and names **one** root cause with a cited evidence chain. `remediator` turns that into the smallest possible patch — capped at twelve changed lines by the write path, not by the prompt. After a human merges, `verifier` independently checks recovery, and opens a **revert PR** if the fix didn't work.

```bash
make demo                                                    # offline incident workflow
ESTATE_ADAPTER=fake .venv/bin/python -m warden.agents.demo --live --mode bad_config
```

📄 **[The full ML workflow flowchart](docs/reverie/warden-flow-ml-workflow.png)** — both workflows, every prompt in full, model per node, and the revert loop.

---

## Live models

Offline runs use scripted models and need no key. For live generation, copy `.env.example` to `.env`:

```bash
DELIVER_MODEL=azure/gpt-5.6-sol      # Gemini and Vertex direct; Azure/OpenAI/Anthropic via LiteLLM
AZURE_API_KEY=...
AZURE_API_BASE=https://<resource>.openai.azure.com/
DEPLOY_TARGET=containerapp
DEPLOY_URL=https://your-site.com     # optional — the run ends on a clickable live site
```

```bash
make dashboard        # → http://localhost:8080/studio
```

The studio streams the run live: clone, each node lighting up with the real artifact it produced, the pull request, and the deployed URL.

---

## Status and known limitations

DELIVER runs live on Azure GPT-5.6 and opens real pull requests through a GitHub App. OPERATE runs against a real AKS cluster or a scripted fixture estate.

**What broke, and what we did about it.** Our first live PR looked correct, passed the Validate node, and deployed nothing — it gated deploy on `refs/heads/main` against a repo whose default branch is `master`, so the job skipped silently behind a green checkmark. Two more followed: a Trivy action tag that doesn't exist, and an installer that rate-limits on shared runners.

- **Fixed.** `pipeline_rules()` is now the single definition of the branch gate and scanner rules. A fresh run emits `github.ref_name == github.event.repository.default_branch` and a containerized scanner, with no human edits.
- **Fixed.** The containerize prompt now separates *pinning* from *pinning to something maintained* — the old rule produced a correctly-pinned `alpine:3.20.3`, a series that went end-of-life in April 2026 and carried 21 HIGH/CRITICAL findings.
- **Still open.** Validate reads text, so it cannot know whether an action tag resolves or a distro is EOL. All three defects above got past it and were caught the moment the pipeline ran. That's a designed boundary: Validate is the cheap gate on every generation, the generated pipeline's own scan stage is the expensive one on merge.
- **Next.** Grow the reflection node into a loop that reads the Actions result and repairs until the run is green.

The pattern under all of it: **we were asking the model for facts the system already had.** We clone the repo, so the default branch is on disk. Facts get injected as data or enforced after generation; only judgment goes to the model.

---

## Safety

- Developers own the application code and review every generated artifact.
- A pull request is the collaboration boundary. Deploying is a separate, explicit `--apply`.
- Secrets are referenced through CI/CD secrets and env config, never written into generated artifacts.
- Every tool call is policy-checked, budget-capped, and written to the audit trail.

---

## Commands

| Command | Purpose |
|---|---|
| `./setup.sh --deliver` | Offline delivery workflow |
| `make dashboard` | Live studio → `localhost:8080/studio` |
| `make deliver-live` | Delivery with a live model |
| `make demo` | Offline incident workflow |
| `make bench-deliver` | Offline replay of the workflow-vs-single-prompt scorer |
| `warden bench-deliver --live -n 5` | The real head-to-head: same model, 5 samples each |
| `make test` | Test suite |
| `make probe` | Print the policy matrix |

## Layout

```text
warden/delivery/       DELIVER orchestration, source, PR publishing, deploy targets
warden/agents/         node prompts (definitions.py) + ADK runtime; OPERATE agents
warden/control_plane/  policy, budgets, manifests, audit store
warden/tools/          scoped repository, source and infrastructure tools
warden/dashboard/      FastAPI API + live studio UI
manifests/agents/      OPERATE nodes — triage, diagnostician, remediator, verifier
manifests/delivery/    DELIVER nodes — assess, containerize, pipeline, deploy_plan, verify
docs/reverie/          flowcharts, node documentation, benchmark material
docs/HANDOFF.md        full status and open-problem write-up
```
