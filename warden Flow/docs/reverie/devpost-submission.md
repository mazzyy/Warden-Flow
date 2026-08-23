# Warden Flow — Devpost submission copy

**Track:** ML Prompt Engineering
*(Paste into the matching Devpost fields. Main image: `warden-flow-lifecycle.png`. Attach the docs as supporting material.)*

---

## Tagline
An AI DevOps engineer built as a multi-node LLM workflow — it ships your service and keeps it healthy — where structure, not a bigger prompt, is what makes the output safe.

## Inspiration
Ask a single LLM to "write me a Dockerfile" or "read these logs and fix it" and it hands you something confident, plausible, and often dangerous — an image that runs as root from an unpinned base, or a patch that fixes the bug and quietly breaks three other things. The failure isn't intelligence; it's that nothing stops the model from doing more than the task, citing nothing, and skipping the checks. We wanted to show the fix is **workflow design**: decompose the job into small, typed, individually-verifiable LLM queries, and the careless behaviors have nowhere to hide.

## What it does
Warden Flow is one structured-prompting engine running two workflows:

- **DELIVER** (proactive): assess a repo → generate a production Dockerfile → a CI/CD pipeline → a Kubernetes deploy plan → **human review** → verify every artifact.
- **OPERATE** (reactive): an alert → triage → diagnose (with a cited evidence chain) → fix via a pull request → **human review** → verify recovery.

Every node runs one narrowly-scoped LLM query, returns a **typed object** (enforced by a Pydantic schema), and hands that structure to the next node. The only step that changes production is a human merge.

## How we built it — the prompt engineering
Three principles run through both workflows: **one job per node** (each prompt decides one thing and is told what *not* to do), **typed output enforced** (a node can't answer a `root_cause` or a `runs_as_nonroot` field with waffle), and **structured handoffs** (each node consumes the previous node's typed result, not the raw world). The constraints live *in the prompts* — "cite the specific log line, not a paraphrase"; "pinned base, multi-stage, non-root, no baked secret; record each" — and each defends a specific failure mode.

We also built a **Reflection node**: after a run it critiques the workflow's own prompts and proposes the single highest-leverage improvement. That's a prompt-optimization loop, in the tool.

## The proof (two benchmarks, both computed)
The track's core question is whether structured prompting beats a single prompt. We answer it with runnable, auto-scored benchmarks on the *same* task and the *same* model — only the structure differs.

- **`warden bench-deliver`** (containerize): a single "write me a Dockerfile" prompt scores **0/5** on a best-practice checklist (unpinned base, root user, secret baked into a layer, no healthcheck, single stage); the workflow scores **5/5**. Both build; only one is safe to ship. Every check is computed from the Dockerfile text.
- **`warden bench`** (fix an incident): the single prompt fixes a one-character typo *and* makes three unverified collateral edits; the workflow makes one scoped, evidence-backed change. Scored from a real diff.

## Model selection — verified on Azure GPT‑5.6
Each node's model is declared in a version-controlled manifest and is swappable without touching orchestration: **Gemini** natively, or **Azure OpenAI GPT‑5.6 / OpenAI / Anthropic** through one resolver (LiteLLM). We ran the DELIVER nodes live on **Azure GPT‑5.6** and confirmed the typed schemas come through cleanly via Azure's Responses API — the same governance, budgets, and structured output as Gemini, on a different provider.

## Challenges
Getting a node to say "the evidence is inconclusive" or "this fact isn't in the files I read" instead of inventing a tidy answer; making the containerizer enforce security constraints rather than emit a generic template; and wiring a second model provider (Azure) through the same runtime so structured output still holds.

## Accomplishments
Two workflows where no node can silently break production — read-only investigation, generators capped and constrained, and a human gate on the only step that applies anything — plus benchmarks that *prove* the structured approach wins, and a live run on a non-default model provider.

## What we learned
Prompt engineering at the workflow level beats prompt engineering at the sentence level. You get reliability not by asking the model to be more careful, but by structuring the task so carelessness is impossible — and by verifying, with a scored comparison, that the structure actually pays off.

## What's next
Wiring the optional Apply node to push to a registry and deploy (Azure Container Registry + AKS); routing high-volume nodes to cheaper models; and feeding the Reflection node's suggestions back into the prompts automatically.

## Built with
Google Gemini 3.5 · Azure OpenAI GPT‑5.6 · LiteLLM · Agent Development Kit (ADK) · Pydantic structured outputs · GitOps pull-request workflow · Python

## Submission artifacts (docs/reverie/)
- `warden-flow-lifecycle.png` — the workflow flowchart (both lanes, human inputs, model selection, actions)
- `delivery-workflow.md` — the DELIVER nodes, the failure each prompt defends against, and the Azure run
- `node-documentation.md` — the OPERATE nodes in the same depth
- `workflow-vs-single-prompt.md` — the incident comparison + scoring table
- Repo: https://github.com/mazzyy/Warden-Flow
