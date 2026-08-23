# Reverie Hacks 2026 — "Warden Workflow" submission roadmap

**Track:** ML Prompt Engineering · **Deadline:** Aug 24, 12:00am CDT = **07:00 Berlin, tomorrow** · **~15 hours out**
**Decision:** Do NOT build anything new. Repackage the existing Warden workflow into this track's three required artifacts.

---

## 1. The one-line difference

**Google Warden** was judged as a *deployed system* — hosted URL, live unedited video, security governance, infrastructure.
**Reverie Warden** is judged as a *prompt-engineering workflow* — three documents describing how you orchestrate LLMs. No deploy, no infra scoring, video optional.

Same brain. Completely different packaging. You are submitting an **analysis of the workflow**, not the workflow itself.

---

## 2. What we're actually submitting

The ML Prompt Engineering track requires exactly three things — nothing else counts:

1. **Workflow flowchart (PNG)** — showing human inputs, LLM queries, model selection, and actions.
2. **Workflow-vs-single-prompt comparison** (video or document) — proof your staged workflow beats a naive one-shot prompt.
3. **Node documentation** — detailed writeup explaining each node.

Everything we build tonight maps to one of those three. If it doesn't, we don't build it.

---

## 3. The reframe: 4 agents → 5 workflow nodes

Warden's four agents become the workflow's nodes. We **promote the human PR review to its own node** because the track explicitly requires human input, and it's your best structural asset.

| # | Node | LLM query does | Model tier | Structured output |
|---|------|----------------|------------|-------------------|
| 1 | **Triage** | Dedupe + severity + go/no-go gate | cheap/fast (Flash/Gemma) | `TriageVerdict` |
| 2 | **Diagnosis** | Hypothesis + forced evidence chain (read-only tools) | strongest | `Diagnosis` |
| 3 | **Remediation** | Smallest patch → opens a PR only | strongest | `ProposedPatch` |
| 4 | **Human-in-the-Loop Review** | *No LLM.* Human merges / rejects the PR | — human input — | merge signal |
| 5 | **Verification** | Did it recover? Close or open a revert | cheap/fast | verdict |

The three prompt-engineering techniques already in your code that we foreground:
- **Structured outputs** — every node is pinned to a Pydantic schema (`output_schema`), not free text.
- **Structured handoffs** — the diagnosis's hypothesis + root cause + evidence chain is *piped verbatim* into the remediation prompt. Nodes don't re-derive; they consume structure.
- **Evidence-forcing prompts** — "every claim in root_cause must be traceable to a tool output; cite the specific log line, not a paraphrase." That single instruction is the whole reason the workflow beats a single prompt.

---

## 4. How it differs from the Google Warden submission

| Axis | Google Warden | Reverie Warden Workflow |
|------|---------------|--------------------------|
| Framing | Governed SRE agent fleet | Structured multi-node LLM workflow |
| Hero claim | "No prod credentials — only write primitive is a PR" (governance) | "Structured staged prompting beats a single prompt" (prompt design) |
| Star of the show | Policy proxy / control plane / audit log | The node prompts, structured outputs, and handoffs |
| Deliverables | Hosted URL, live video, arch diagram, repo | Flowchart PNG, comparison, node docs |
| Judged on | Deployment, security, robustness | Workflow design, prompt optimization, human input |
| Human input | A governance feature | A required, headlined workflow node |
| Code changes needed | — | **None.** Extraction + documentation only |
| Azure/other LLM | N/A | **Not used tonight** — save the $1000 for later; Warden's already on Gemini |

The governance story (policy proxy, manifests, budgets) is **demoted to a supporting paragraph** — reframed as "guardrails on generation," not the headline. Leading with it in a prompt-engineering track reads as a systems project in disguise.

---

## 5. Stages (time-boxed, cut from the bottom if time runs out)

**Minimum viable submission = all three artifacts exist at basic quality.** Depth is added top-down.

### Stage 0 — Rules check + prompt extraction · ~30 min · *mostly done*
- [ ] 5-min skim of Reverie rules/Discord for any "must be built during the event" clause.
- [x] Extract the real node prompts from `agents/definitions.py` and the handoff prompts from `orchestrator.py`. **Done.**

### Stage 1 — Node documentation · ~2h · CORE
For each of the 5 nodes, one section: purpose → the actual prompt template → model choice + why → input/output schema → **the failure mode the structure defends against**. This is the substance judges score.
- **Done =** a `node-documentation` doc with all 5 nodes, real prompts quoted, rationale per node.

### Stage 2 — Single-prompt vs workflow comparison · ~3h · HIGHEST VALUE
Pick one incident: the **bad-config crashloop** (env var typo → PAYMENT_ENDPOINT malformed → crashloop).
- **Baseline:** one naive prompt — "here are the logs, write the fix" — capture its output (expected: plausible but wrong/unsafe/unscoped, e.g. bumps resources or edits the wrong file, no evidence).
- **Workflow:** the staged Warden output (correct: reverts the specific value, cites the deploy, scoped patch, PR body a human can approve in 30s).
- **Scoring table** across: correctness, safety/blast-radius, hallucination, evidence traceability, human-reviewability, token cost.
- **Done =** a side-by-side doc with both raw outputs + the scoring table. (Optional stretch: a short screen-capture video.)

### Stage 3 — Flowchart PNG · ~1.5h
5 nodes left-to-right: signal → Triage (gate) → Diagnosis → Remediation → **Human Review (highlighted)** → Verification, with revert loop back. Annotate each node with model tier, tools, and structured output. Human input node visually distinct.
- **Done =** a clean exported PNG. (Build as HTML/SVG, render to PNG.)

### Stage 4 — Submission text + package + submit · ~1h
- [ ] Devpost project text: inspiration, what it does, how the workflow is built, prompt-engineering choices, what's next.
- [ ] Attach the 3 artifacts. Optional: link the repo.
- [ ] **Submit with buffer — target done by ~03:00 Berlin, not 06:59.**

---

## 6. Cut line

If time collapses, ship in this priority: **flowchart (required) → comparison (highest scoring) → node docs (deepest).** All three are required fields, so the real trade-off is depth, not existence. Never let Stage 4 (the actual submit) get squeezed — an unsubmitted perfect project scores zero.
