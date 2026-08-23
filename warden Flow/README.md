# Warden Flow

**An AI DevOps engineer built as a multi-node LLM workflow — it ships your service *and* keeps it healthy — and proves, with built-in benchmarks, that structured staged prompting beats a single prompt.**

Warden Flow is a prompt-engineering system with a full lifecycle, on one engine:

- **DELIVER** (proactive) — assess a repo → generate a Dockerfile → a CI/CD pipeline → a deployment plan → human review → verify.
- **OPERATE** (reactive) — an alert → triage → diagnose → fix via PR → human review → verify.

The interesting part is *how it prompts*: instead of asking one model to "read this and do it," it decomposes each job into small, typed, individually-scoped nodes, hands structured output from each node to the next, and gates the only production-changing step behind a human. Models are swappable per node — Gemini by default, **Azure OpenAI GPT‑5.6**, OpenAI, or Anthropic via one resolver.

It ships with things most workflows don't:

- **`warden bench`** and **`warden bench-deliver`** — runnable benchmarks that solve the *same* task two ways (a single naive prompt vs. the staged workflow) and **score them from the real output**, not a claim.
- **A Reflection node** — a post-run LLM critic that proposes the single highest-leverage change to a node's prompt. The prompt-optimization loop, in the tool.

---

## Quickstart

```bash
./setup.sh                 # venv + deps + .env, then run one incident offline (free, no key)
./setup.sh --deliver       # the DELIVER workflow: repo → Dockerfile → pipeline → deploy plan
./setup.sh --bench         # incident: workflow vs single prompt + reflection (free, offline)
./setup.sh --bench-deliver # containerize: workflow vs single prompt, scored on best practices
./setup.sh --test          # 123-test suite + policy probe
./setup.sh --dashboard     # build + serve the live dashboard on http://localhost:8080
```

Offline runs use scripted models — deterministic, free, no credentials. For real models add a key to `.env` and use `--live` / `make bench-live` / `make deliver-live` / `make bench-deliver-live`. To run DELIVER on **Azure GPT‑5.6**, set `DELIVER_MODEL=azure/gpt-5.6-sol` plus `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` in `.env`. See `docs/reverie/delivery-workflow.md`.

---

## The benchmark — why nodes beat one prompt

```bash
make bench        # or ./setup.sh --bench
```

One incident (a GitOps deploy set `PAYMENT_ENDPOINT` to `htps://…` — a one-character typo — and crashlooped checkout-svc), solved both ways, scored side by side:

```
SCOREBOARD                    single prompt       warden flow
  fixed the root cause        yes                 yes
  lines changed               4                   1
  within 12-line blast radius yes                 yes
  collateral edits            3                   0
  evidence cited              0                   3
  confidence reported         n/a                 0.93
```

Both fix the bug. But the single prompt also bumps memory (the crashloop was never OOM), "tunes" a timeout because a commit message mentioned it, and nudges a probe — three unverified changes riding into production on the back of one real fix. The workflow changes exactly one line, cites three pieces of evidence, and reports its confidence. **Every number above is computed from a real diff of each approach's output**, not asserted.

Then the **Reflection node** reads the run and proposes one concrete prompt improvement — e.g. tightening the verifier to name the exact metric and threshold it checked before closing an incident. That's the workflow tuning its own prompts.

---

## The five nodes

Each node runs one narrowly-scoped LLM query, returns a **typed object** (enforced by a Pydantic `output_schema`), and hands that structure to the next node.

| # | Node | LLM query | Structured output | Model / budget |
|---|------|-----------|-------------------|----------------|
| 1 | **Triage** | Real, duplicate, worth escalating? | `TriageVerdict` | flash · 20k tok |
| 2 | **Diagnosis** | One root cause, with a cited evidence chain | `Diagnosis` | flash · 120k tok |
| 3 | **Remediation** | Smallest fix, ≤12-line diff, opens a PR only | `ProposedPatch` | flash · 120k tok |
| 4 | **Human Review** | *(no LLM)* merge or reject the PR | human decision | — |
| 5 | **Verification** | Did it actually recover? Close or revert | free reasoning → tool | flash · 40k tok |

Plus the meta node:

| ✦ | **Reflection** | Critique the run, propose a better prompt | `Reflection` | flash · 40k tok |

Full per-node documentation — the exact prompts, the model/budget rationale, and the specific failure each design choice defends against — is in [`docs/reverie/node-documentation.md`](docs/reverie/node-documentation.md). The workflow diagram is [`docs/reverie/warden-flow-workflow.png`](docs/reverie/warden-flow-workflow.png).

---

## The three prompt-engineering principles

1. **One job per node.** Each prompt decides exactly one thing and is told what *not* to do ("diagnose ONE root cause"; "you can read, you cannot change anything"). A node that diagnoses *and* fixes does both worse.
2. **Typed output, enforced.** Nodes can't answer a `root_cause` field with "probably something in the config" — they must commit to discrete, machine-checkable claims.
3. **Structured handoffs.** A node consumes the *typed output* of the one before it, not the raw world. The diagnosis's cited evidence chain is reassembled field-by-field into the remediation prompt, so the fixer reasons over vetted facts.

The single most important line in the system is in the Diagnosis prompt: *"every claim in root_cause must be traceable to something a tool actually returned; cite the specific log line, not a paraphrase."* That one instruction turns a plausible-story generator into an investigator that shows its work.

---

## How it runs

```
signal ─→ Triage ─→ Diagnosis ─→ Remediation ─→ [Human merges PR] ─→ Verification ─→ resolved
            (gate)   (read-only)   (PR only)                            (or revert)
```

- **Nodes are configuration, not code.** Every node is declared in a version-controlled manifest (`manifests/agents/*.yaml`) — model, tools, token budget, and blast radius. Routing Triage to a cheaper model is a one-line change.
- **No node changes production.** A node's only write primitive is *proposing* a pull request; a human owns *applying* it. This is why the fleet needs no production credentials.
- **A live dashboard** (`make dashboard`) shows an incident move through the nodes in real time, with an audit log, a kill switch, and the policy matrix.

### Configuration

Copy `.env.example` to `.env`. Offline runs (`demo`, `bench`, `test`) need nothing. Live runs need one model credential:

- **Gemini API** (free tier, great for iterating): `GOOGLE_GENAI_USE_ENTERPRISE=0` + `GOOGLE_API_KEY=...`
- **Vertex AI**: `GOOGLE_GENAI_USE_ENTERPRISE=1` + `gcloud auth application-default login`

To open real pull requests, point `GITHUB_OWNER` / `GITOPS_REPO` at a GitOps repo and provide a GitHub App (recommended) or a fine-grained token. Without one, remediation stays a dry-run.

---

## Commands

| Command | What it does |
|---------|--------------|
| `make demo` / `./setup.sh` | One incident end to end, offline and free |
| `make bench` / `./setup.sh --bench` | Workflow vs single prompt, scored + reflection |
| `make demo-live` / `make bench-live` | The same, against real Gemini |
| `make test` | 123-test suite (no cloud, no key, no spend) |
| `make probe` | The policy matrix (agent × tool) |
| `make dashboard` | Build + serve the live dashboard on :8080 |
| `make check` | Lint + test + the "no agent can write to the cluster" assertion |

---

## Repository layout

```
warden/agents/        the nodes: definitions (prompts), orchestrator, runtime
warden/bench.py        the workflow-vs-single-prompt benchmark + reflection
warden/control_plane/  manifests registry, policy, budget, audit store
warden/tools/          the read/PR tool surface, behind a policy proxy
manifests/agents/      the four incident nodes, as versioned YAML
manifests/reflection.yaml  the meta node
docs/reverie/          node documentation, the benchmark comparison, the flowchart
```

---

*Built with Google Gemini 3.5 Flash, the Agent Development Kit (ADK), Pydantic structured outputs, and a GitOps pull-request workflow.*
