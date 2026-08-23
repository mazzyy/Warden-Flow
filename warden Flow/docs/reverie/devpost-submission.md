# Warden Flow — Devpost submission copy

**Track:** ML Prompt Engineering
*(Paste these into the matching Devpost fields. Attach the flowchart PNG as the main image and the two docs as supporting material.)*

---

## Tagline
A multi-node LLM workflow that turns a raw production alert into a reviewed, one-line fix — where structure, not a bigger prompt, is what makes the fix safe.

## Inspiration
Ask a single LLM to "read these logs and fix the service" and it will hand you something confident, plausible, and often dangerous — it fixes the real bug *and* bumps memory it didn't need to, "tunes" a timeout a commit message mentioned, and rewrites a file it reconstructed from memory. The failure isn't intelligence; it's that nothing stops the model from doing more than the task. We wanted to show that the fix for that is **workflow design**: decompose the job into small, typed, individually-verifiable LLM queries, and the careless behaviors have nowhere to hide.

## What it does
Warden Flow watches a production estate and, when something breaks, runs the incident through five specialized nodes:

1. **Triage** — a cheap gate that dedupes and decides if a signal is even worth escalating. Most alerts die here.
2. **Diagnosis** — a read-only node that must produce a hypothesis with an **explicit, cited evidence chain**, or lower its own confidence.
3. **Remediation** — turns that diagnosis into the *smallest* change, capped to a 12-line blast radius, and opens a pull request. It cannot touch the cluster and cannot merge.
4. **Human Review** — a required human-in-the-loop node. The workflow halts until a person merges or rejects the one-line PR. This is the only step that changes production.
5. **Verification** — after the merge, independently checks whether the service actually recovered, and opens a revert PR if it didn't.

## How we built it — the prompt engineering
The whole system is an exercise in three techniques:

- **One job per node.** Each prompt decides exactly one thing and is explicitly told what *not* to do ("diagnose ONE root cause"; "you can read, you cannot change anything"). A node that diagnoses *and* fixes does both worse.
- **Typed output, enforced.** Each decision node is pinned to a Pydantic schema via the runtime's `output_schema`. The model can't answer a `root_cause` field with "probably something in the config" — it must commit to discrete, machine-checkable claims.
- **Structured handoffs.** Nodes don't re-read the raw world; they consume the *typed output* of the previous node. The diagnosis's cited evidence chain is reassembled field-by-field into the remediation prompt, so the fixer reasons over vetted facts, not 400 lines of crashloop logs it might re-interpret differently.

The single most important prompt line in the system is in Diagnosis: *"every claim in root_cause must be traceable to something a tool actually returned; cite the specific log line, not a paraphrase."* That one instruction converts a plausible-story generator into an investigator that shows its work — and it's the difference between a fix you can trust and one you can't.

Model selection is configuration: every node is declared in a version-controlled manifest (model, tools, token budget, tool-call cap, blast radius, approval mode). The high-volume Triage node runs on the tightest budget; the two reasoning nodes get the large one. Swapping Triage to a smaller/cheaper model is a one-line manifest change.

## The proof (workflow vs. single prompt)
We ran the *same real incident* — a GitOps deploy that set `PAYMENT_ENDPOINT` to `htps://…` (a one-character typo) and crashlooped checkout-svc — two ways. The single prompt fixed the typo **and** bumped memory (wrong cause), "tuned" an unrelated timeout, and in sampled runs swapped the unfamiliar-looking container image, which would have deleted the running service. Warden Flow produced a **one-line PR** restoring `https`, with three cited pieces of evidence and a 0.93 confidence score, that a human approved in thirty seconds. Full side-by-side with a scoring table is in the comparison document.

## Challenges
Getting the Diagnosis node to say "the logs are inconclusive" instead of inventing a tidy story; making the Remediation node return a whole file it actually read rather than reconstructing one from memory; and designing the blast-radius cap so a well-intentioned "modernize this" edit is refused at the write path rather than trusted.

## Accomplishments
A workflow where no node can silently break production: read-only diagnosis with forced evidence, a fixer capped to a tiny diff, and a human gate on the only step that applies anything.

## What we learned
Prompt engineering at the workflow level beats prompt engineering at the sentence level. You get reliability not by asking the model to be more careful, but by structuring the task so carelessness is impossible.

## What's next
Routing Triage to a smaller model (e.g. Gemma) for cost; incident-memory recall so repeat failures are diagnosed faster; and extending the estate beyond the demo service.

## Built with
Google Gemini 3.5 Flash · Agent Development Kit (ADK) · Pydantic structured outputs · GitOps pull-request workflow · Python

## Submission artifacts
- `warden-flow-workflow.png` — the ML workflow flowchart (human inputs, LLM queries, model selection, actions)
- `workflow-vs-single-prompt.md` — the comparison + scoring table
- `node-documentation.md` — detailed per-node documentation
- Repo: https://github.com/mazzyy/Warden-Flow
