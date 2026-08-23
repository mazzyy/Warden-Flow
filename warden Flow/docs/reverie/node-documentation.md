# Warden Flow — Node Documentation

**Reverie Hacks 2026 · ML Prompt Engineering track**

Warden Flow is a multi-node LLM workflow that turns a raw production alert into a reviewed, minimal code fix. It does *not* do this with one large prompt. It does it as a chain of narrowly-scoped nodes, where each node runs one specialized LLM query, is forced to return a **structured object** (not free text), and hands that structure to the next node. The design thesis of the whole submission is:

> A production fix is only as trustworthy as the reasoning behind it. You get trustworthy reasoning by decomposing the problem into small, individually-verifiable LLM queries with typed outputs — not by asking one model to do everything at once.

This document explains every node: what it does, the exact prompt that drives it, the model and budget it runs under, the structured output it must return, and — most importantly — **the specific failure mode each design choice is defending against.**

---

## The workflow at a glance

| # | Node | LLM query | Structured output | Action taken |
|---|------|-----------|-------------------|--------------|
| 1 | **Triage** | Is this real, is it a duplicate, is it worth escalating? | `TriageVerdict` | Gate: escalate or close |
| 2 | **Diagnosis** | What is the one root cause, and what evidence proves it? | `Diagnosis` | Produce hypothesis + evidence chain |
| 3 | **Remediation** | What is the smallest change that fixes exactly that root cause? | `ProposedPatch` | Open a pull request |
| 4 | **Human Review** | *(no LLM)* Is this fix safe to merge? | merge / reject signal | Human merges or closes the PR |
| 5 | **Verification** | Did the merged fix actually restore health? | free reasoning → tool call | Close incident, or open a revert PR |

Three prompt-engineering principles run through all of it:

1. **One job per node.** Each prompt is told to decide *one* thing and explicitly told what *not* to do. A node that tries to diagnose *and* fix will do both worse.
2. **Typed output, enforced.** Nodes 1–3 are pinned to a Pydantic schema via the model runtime's `output_schema`. The model cannot return prose where a decision is required; it must fill fields.
3. **Structured handoffs.** A node does not re-read the raw world. It consumes the *typed output* of the node before it. The diagnosis's evidence chain is piped verbatim into the remediation prompt, so the fixer reasons over vetted facts, not raw logs.

---

## Cross-cutting technique: structured output + structured handoff

This is the mechanism that makes the whole thing more than a chatbot with tools.

**Structured output.** Each decision node declares a schema:

```python
class Diagnosis(BaseModel):
    hypothesis: str        # what is wrong, in one sentence
    root_cause: str        # the specific change or condition responsible
    evidence: list[Evidence]   # facts supporting the hypothesis
    suggested_fix: str
    confidence: float      # 0.0–1.0
```

The runtime enforces this shape on the node's final answer. That does two things at once: it *forces the model to commit* to discrete claims (a `root_cause` field cannot be filled with "it's probably something in the config, hard to say"), and it makes the output *machine-checkable* by the next node and by the audit trail.

**Structured handoff.** The orchestrator does not paste the diagnosis text into the next prompt. It reassembles the *fields* into the remediation query:

```python
prompt = (
    f"Hypothesis: {diagnosis.hypothesis}\n"
    f"Root cause: {diagnosis.root_cause}\n"
    f"Suggested fix: {diagnosis.suggested_fix}\n"
    f"Evidence:\n"
    + "\n".join(f"  - [{e.source}] {e.detail}" for e in diagnosis.evidence)
    + "\n\nOpen a pull request that fixes this."
)
```

The remediator therefore starts from a clean, cited root cause — not from 400 lines of crashloop logs it would have to re-interpret (and might re-interpret *differently* than the diagnostician did). Every handoff is a checkpoint where reasoning is frozen into typed facts.

---

## Node 1 — Triage

| | |
|---|---|
| **Model** | `gemini-3.5-flash` |
| **Budget** | 20,000 tokens · 6 tool calls — the tightest tier in the fleet, because this node runs on *every* alert |
| **Tools** | `get_alert_context`, `recall_similar_incidents` (read-only) |
| **Scope** | `memory:incidents:read` · blast radius 0 (cannot write anything) |
| **Output schema** | `TriageVerdict` |

**Output schema**

```python
class TriageVerdict(BaseModel):
    severity: Severity              # critical | high | medium | low | noise
    escalate: bool                  # True if the fleet should investigate
    duplicate_of: str | None        # existing incident id if this is a repeat
    reasoning: str                  # one or two sentences on why
```

**The prompt**

> You are the first responder for a production estate. A signal has arrived. Decide three things and nothing else: how severe this is; whether it is a duplicate of an incident already open; whether it is worth waking the rest of the fleet for. Call `get_alert_context` first. If the signal has a recognisable failure signature, call `recall_similar_incidents` before deciding. […] Understand what escalation costs HERE, because it is not what it costs on a human rota. Escalating does not wake a person at 3am. It wakes three agents, for a few cents and about thirty seconds […]. So the asymmetry runs the other way from the one you are used to: escalating something harmless is cheap, and failing to escalate something real means nobody looks at it at all. In particular, "no user impact right now" is not the same as "no incident". A blocked or failed rollout is a latent outage even while every replica is serving […].

**Prompt-engineering choices and the failure they defend against**

- **The `escalate` boolean is a hard routing gate.** Making the model commit to a typed yes/no — not a paragraph — lets the orchestrator cheaply terminate the workflow at Node 1 for the 90% of alerts that are noise. *Defends against:* burning the expensive diagnosis budget on non-incidents.
- **Explicitly re-anchoring the cost model** ("escalating wakes agents, not a person"). An LLM's prior, learned from human ops writing, is that paging is expensive and should be rare. That prior is *wrong* here and produces over-suppression. *Defends against:* a false negative where a real fault is silently closed because the model was being "considerate."
- **The named counter-example** ("no user impact now ≠ no incident; a blocked rollout is a latent outage"). *Defends against:* the single most likely triage miss in this estate — a stuck rollout that looks healthy because the old revision is still serving.
- **"Decide three things and nothing else."** *Defends against:* scope creep, where triage starts diagnosing and spends its tiny budget doing the next node's job badly.

---

## Node 2 — Diagnosis

| | |
|---|---|
| **Model** | `gemini-3.5-flash` |
| **Budget** | 120,000 tokens · 25 tool calls — the largest in the fleet; this is where reasoning has to earn its keep |
| **Tools** | `describe_workload`, `get_workload_logs`, `recent_deploys`, `query_metrics` — **all read-only** |
| **Scope** | `cluster:demo:read` · blast radius 0 |
| **Output schema** | `Diagnosis` |

**The prompt**

> You are diagnosing a production failure. You can read; you cannot change anything, anywhere. Do not propose a fix as though you could apply it. Work from evidence, in roughly this order: `describe_workload` — what state is it actually in? `get_workload_logs` — what did it say before it died? `recent_deploys` — what changed just before this started? `query_metrics` — confirm the blast radius. **Your output is a hypothesis with an explicit evidence chain. Every claim in root_cause must be traceable to something a tool actually returned; cite the specific log line or field, not a paraphrase.** If the evidence does not support a confident conclusion, say so in the confidence score rather than inventing a tidy story. […] Diagnose ONE root cause — the one that explains the failure in the logs. Do not list every unusual thing you noticed. […] an unfamiliar image, an inline command or a hand-rolled entrypoint may be entirely deliberate. Saying "this also looks wrong to me" invites a fix that breaks something which was working.

**Prompt-engineering choices and the failure they defend against**

- **Forced evidence chain — the single most important technique in the workflow.** The `evidence: list[Evidence]` field, plus "every claim in `root_cause` must be traceable to a tool output; cite the specific line, not a paraphrase," turns the model from a plausible-story generator into an investigator that must show its work. *Defends against:* hallucinated root causes — the failure mode that makes a single naive prompt unsafe to act on.
- **The prescribed tool order** (state → logs → change → metrics). *Defends against:* jumping to a conclusion from the first log line before establishing what actually changed.
- **`confidence: float` + "say inconclusive rather than invent a tidy story."** Calibrated uncertainty is a first-class output, not an afterthought. *Defends against:* false confidence propagating downstream into a wrong fix that a reviewer trusts.
- **"Diagnose ONE root cause; an unfamiliar image may be deliberate."** This is a scar from a real run: given a workload with a hand-rolled entrypoint, the model flagged the image as "wrong" and proposed replacing it, which would have broken a working cluster. *Defends against:* over-diagnosis, where noticing many odd things leads to a destructive multi-part fix.
- **"You can read; you cannot change anything."** Reinforced by a zero-write scope in the manifest. *Defends against:* the model proposing an apply-style action the node has no authority to take.

---

## Node 3 — Remediation

| | |
|---|---|
| **Model** | `gemini-3.5-flash` |
| **Budget** | 120,000 tokens · 20 tool calls |
| **Tools** | `list_repo_files`, `read_repo_file`, `propose_patch` |
| **Scope** | `repo:estate-gitops:read`, `repo:estate-gitops:write-pr` — **no cluster write, cannot merge** |
| **Blast radius** | max 3 files · **max 12 changed lines**, enforced at the write path |
| **Approval** | `required` — this is the hard gate into Node 4 |
| **Output schema** | `ProposedPatch` |

**Input (structured handoff from Node 2):** hypothesis + root cause + suggested fix + the full evidence list, reassembled by the orchestrator.

**The prompt**

> You turn a diagnosis into the smallest change that fixes it. You cannot reach the cluster. Your only action is `propose_patch`, which opens a pull request that a human reviews and merges. Write for that human. Call `list_repo_files` FIRST to find the exact path, then `read_repo_file`. Do not guess paths […]. Return the complete new contents of the file you read — not a diff, not a fragment. Base it on what `read_repo_file` actually returned: never reconstruct a file from memory, because you will silently drop the parts you did not think to include. Change as little as possible […]. Patch ONLY what the diagnosis names as the root cause. Never change an image tag, delete a command block, or restructure a manifest as a side effect […]. The rationale you pass becomes the pull request body. It should let a reviewer who has not seen the incident decide in thirty seconds whether to merge […]. If you are not confident the patch is right, say that in the rationale.

**Prompt-engineering choices and the failure they defend against**

- **"`list_repo_files` FIRST, then `read_repo_file`, do not guess paths."** *Defends against:* hallucinated file paths — the model confidently editing `k8s/deployment.yaml` when the file is actually `manifests/checkout/deploy.yaml`.
- **"Return the complete new file contents; never reconstruct from memory."** *Defends against:* the model regenerating a file from its training prior and silently dropping the fields it didn't think to include — a subtle, dangerous corruption.
- **"Patch ONLY the root cause; never change an image tag or entrypoint as a side effect,"** backed by the 12-line blast-radius cap enforced in code. *Defends against:* collateral edits that fix the reported bug while breaking something that was working — the model cannot verify a different image exists, so it must not touch it.
- **"The rationale becomes the PR body; write so a reviewer decides in thirty seconds; state what you couldn't verify."** The prompt is explicitly optimizing the output *for the human in Node 4.* *Defends against:* an opaque diff a reviewer can't safely approve — false confidence is unmergeable, an honest "here's what I couldn't verify" is safe behind review.

---

## Node 4 — Human-in-the-Loop Review

**This node runs no LLM. That is the point.** It is the required human-input stage of the workflow, and it is a first-class node rather than a footnote because the system is *architecturally* blocked here.

**How the block works.** The remediator's manifest sets `approval: required`. After Node 3 opens the PR, the orchestrator sets the incident to `awaiting_merge` and **returns** — the workflow halts. Node 5 (Verification) is only ever triggered by the GitHub webhook that fires *after a human merges.* No human action, no verification, no closure. The human is not advisory; they are load-bearing.

```python
# orchestrator: after remediation
incident.status = IncidentStatus.awaiting_merge
# … the initial alert path does NOT run the verifier.
# Only the post-merge webhook path sets verify=True.
```

**The prompt engineering that makes this node work is all upstream.** A human review node is only as good as the artifact it reviews. Everything Nodes 2 and 3 were told to do — cite specific evidence, produce a minimal diff, keep the blast radius tiny, write a 30-second PR body, confess low confidence — exists to make *this* decision fast and safe. The human is reviewing a decision-ready object, not raw model output.

**Why it belongs in the workflow diagram.** The human's merge-or-reject is the workflow's ground-truth signal: it is the point where machine reasoning is validated by human judgment before anything touches production. It is also the governance seam — the reason no agent in the fleet needs production write access. Its only write primitive is *proposing*; a human owns *applying*.

---

## Node 5 — Verification

| | |
|---|---|
| **Model** | `gemini-3.5-flash` |
| **Budget** | 40,000 tokens · 15 tool calls |
| **Tools** | `query_metrics`, `get_workload_status`, `request_revert` |
| **Scope** | `cluster:demo:read`, `repo:estate-gitops:write-pr` (can propose a revert, cannot apply one) |
| **Output** | free reasoning ending in either "recovered" or a `request_revert` call |
| **Runs** | only after the human merge in Node 4 |

**The prompt**

> The fix has merged and synced. Decide whether it worked. Check `get_workload_status` and `query_metrics`. Compare against what the incident described — a service that is healthy for a different reason has not been fixed. If it recovered, close the incident. If it did not, call `request_revert` with a clear reason. Do not wait and hope. Rolling back a change that did not help is cheap; leaving a broken service in production while you deliberate is not.

**Prompt-engineering choices and the failure they defend against**

- **"Compare against what the incident described — healthy for a different reason is not fixed."** *Defends against:* a false-resolve, where the service happens to look green (e.g. a restart, a traffic dip) and the node closes an incident the patch never actually fixed.
- **"Do not wait and hope … reverting is cheap."** A deliberate action-bias, and the reason this node holds a `write-pr` scope for revert. *Defends against:* an ambiguous half-recovery being left to fester in production.
- **No output schema.** Unlike Nodes 1–3, the verifier's job ends in a *tool call* (`request_revert`) or a plain close, so it reasons freely and acts, rather than filling a form. The structure here lives in the tool contract, not a response schema.

---

## Model and budget selection

| Node | Model | Token budget | Tool-call cap | Why this tier |
|------|-------|-------------:|--------------:|---------------|
| Triage | gemini-3.5-flash | 20,000 | 6 | Runs on every alert; must be the cheapest. Tight cap forces a fast gate. |
| Diagnosis | gemini-3.5-flash | 120,000 | 25 | The reasoning core. Needs room to read four tools and build an evidence chain. |
| Remediation | gemini-3.5-flash | 120,000 | 20 | Must read the real repo file whole and reason about a minimal edit. |
| Human Review | — | — | — | No model. Human judgment. |
| Verification | gemini-3.5-flash | 40,000 | 15 | Bounded check against metrics; cheaper than diagnosis, richer than triage. |

The per-node **budget cap is the real cost lever** in this workflow: a high-volume node is capped tight, the two reasoning nodes get the large budget, verification sits in between. Because every node is declared in a version-controlled manifest, the *model* itself is a one-line change — the high-volume Triage classifier is the obvious candidate to route to a smaller, cheaper model (e.g. Gemma) without touching a line of orchestration code. Model choice and cost control are configuration, not code.

---

## Why nodes, not one prompt

Every design choice above is a defense against a way a single "here's the error, fix it" prompt fails: it hallucinates a root cause it can't support, guesses a file path, reconstructs a file from memory and drops fields, makes collateral edits it can't verify, and reports the whole thing with unearned confidence. Warden Flow doesn't ask the model to be more careful — it *structures the task* so those failures have nowhere to hide: read-only diagnosis with a forced evidence chain, a fixer that starts from vetted facts and is capped to a 12-line diff, and a human gate on the only step that changes anything. The companion comparison document demonstrates each of these failures happening, and not happening, on the same incident.
