# Warden Flow — Structured Workflow vs. Single Prompt

**Reverie Hacks 2026 · ML Prompt Engineering track**

This document runs *one real incident* two ways: once through a single naive prompt, and once through the Warden Flow multi-node workflow. Same incident, same evidence, same model family (`gemini-3.5-flash`). The point is to show, concretely, what the workflow's structure buys you — and what a single prompt costs you.

The short version: the single prompt often produces a fix that *looks* right and would *break production*. The workflow produces a one-line change a human can safely approve in thirty seconds. Everything below is grounded in the project's real demo estate (`estate-gitops/apps/checkout-svc/deployment.yaml`) and the real node prompts.

---

## The incident

A GitOps deploy (revision **r42**, commit `9f2c1ab`, message *"chore: tune payment endpoint and timeouts"*) went out four minutes ago. `checkout-svc` is now crashlooping: **0/3 replicas ready**.

**The broken manifest** (the offending field, plus the fields that will matter in a moment):

```yaml
# apps/checkout-svc/deployment.yaml  (excerpt, post-r42)
containers:
  - name: checkout
    image: python:3.12-slim            # stock image, service runs inline via `command`/`args`
    command: ["python", "-u", "-c"]
    args: [ "...inline HTTP server..." ]
    env:
      - name: PAYMENT_ENDPOINT
        value: "htps://payments.internal/v2"   # ← r42 typo: 'htps' not 'https'
      - name: TIMEOUT_MS
        value: "3000"
      - name: WARMUP_MB
        value: "8"
    resources:
      limits:
        memory: 256Mi                  # sized to WARMUP_MB; not the problem
    readinessProbe:
      httpGet: { path: /healthz, port: http }
```

**The evidence available to any solver** (identical for both approaches):

| Source | Fact |
|--------|------|
| `get_workload_logs` | `FATAL: unsupported URL scheme "htps" in PAYMENT_ENDPOINT` → `sys.exit(1)` |
| `describe_workload` | container `checkout`: CrashLoopBackOff, 7 restarts, exit code 1 |
| `recent_deploys` | r42 *"chore: tune payment endpoint and timeouts"*, 4 min before first failure |
| `query_metrics` | error_rate 1.0, replicas_ready 0/3 |

**The one correct fix:** restore `PAYMENT_ENDPOINT` to `https://payments.internal/v2`. One character. Nothing else in the file should change.

Note the three traps r42 laid, on purpose:
1. The commit message says *"and timeouts"* — bait to also "fix" `TIMEOUT_MS`.
2. The container is a stock `python:3.12-slim` running an inline `command`/`args` — it looks *unusual*, and an eager model reads unusual as broken.
3. There's a `256Mi` memory limit and a crashloop — the single most common reflex for "pods keep restarting" is "give it more memory."

---

## Approach A — the single prompt

One call. Everything in, a fix out. This is the prompt:

```
You are an SRE. The service checkout-svc is crashlooping (0/3 replicas ready).
Here are the logs, the deployment manifest, and the recent deploys.
Find the problem and return the corrected deployment.yaml.

<logs>
FATAL: unsupported URL scheme "htps" in PAYMENT_ENDPOINT
... container checkout: CrashLoopBackOff, 7 restarts, exit code 1 ...
</logs>
<manifest>
...the full deployment.yaml above...
</manifest>
<recent_deploys>
r42 "chore: tune payment endpoint and timeouts", 4 minutes ago
</recent_deploys>
```

**Representative output** (this is the observed failure mode — the model catches the real bug and then keeps going):

```yaml
# "Here is the corrected deployment.yaml:"
containers:
  - name: checkout
    image: python:3.12-slim
    env:
      - name: PAYMENT_ENDPOINT
        value: "https://payments.internal/v2"   # ✔ real fix
      - name: TIMEOUT_MS
        value: "5000"                            # ← "tuned" per the commit message — UNREQUESTED
      - name: WARMUP_MB
        value: "8"
    resources:
      limits:
        memory: 512Mi                            # ← bumped "to stop the restarts" — WRONG cause
    readinessProbe:
      httpGet: { path: /healthz, port: http }
      initialDelaySeconds: 10                    # ← quietly changed
```

> *"I fixed the malformed URL scheme, increased the memory limit to prevent the crashlooping, and tuned the request timeout as noted in the recent deploy."*

**What's wrong with it — even though it "fixed the bug":**

- **Collateral edits it cannot justify.** It bumped `memory` (the crashloop was never OOM — it was `exit(1)` at startup), "tuned" `TIMEOUT_MS` because a *commit message* mentioned timeouts, and nudged the probe. Each is an unverified change riding into production on the back of a real fix.
- **No evidence, no confidence.** The prose asserts three changes with equal, unearned confidence. A reviewer can't tell the one cited fact (`htps` in the logs) from the two guesses.
- **Whole-file rewrite.** The diff touches the entire manifest, so a reviewer must re-read all of it. In sampled runs this is also where the model "modernizes" the odd-looking inline `command`/`args` or swaps the `python:3.12-slim` image for something "proper" — which **deletes the running service.** (This is not hypothetical; the project's own notes record a live run doing exactly this.)
- **Variance.** On other samples the single prompt misses the typo entirely and returns *only* a memory bump — a confident fix for a problem that doesn't exist, leaving the service down.

The single prompt's failure isn't that it's dumb. It's that nothing *stops* it from doing more than the task, citing nothing, and rewriting everything.

---

## Approach B — Warden Flow (the staged workflow)

The same incident, decomposed into typed nodes. This is the real trace (mirrors the live-model run in `warden/agents/fixtures.py`):

**Node 1 · Triage** → `gemini-3.5-flash`, budget 20k/6
```json
{ "severity": "critical", "escalate": true, "duplicate_of": null,
  "reasoning": "checkout-svc has 0/3 replicas ready and no matching open incident." }
```
Not noise, not a duplicate → escalate. (No fix attempted; that's not this node's job.)

**Node 2 · Diagnosis** → read-only, budget 120k/25, forced evidence chain
```json
{
  "hypothesis": "checkout-svc crashloops on startup because PAYMENT_ENDPOINT has a malformed URL scheme.",
  "root_cause": "Revision r42 (commit 9f2c1ab, 4 min ago) set PAYMENT_ENDPOINT to 'htps://payments.internal/v2' — 'htps' instead of 'https'.",
  "evidence": [
    { "source": "get_workload_logs", "detail": "FATAL: unsupported URL scheme \"htps\" in PAYMENT_ENDPOINT" },
    { "source": "describe_workload", "detail": "container checkout: CrashLoopBackOff, 7 restarts, exit code 1" },
    { "source": "recent_deploys",   "detail": "r42 deployed 4 minutes before first failure" }
  ],
  "suggested_fix": "Restore PAYMENT_ENDPOINT to 'https://payments.internal/v2'.",
  "confidence": 0.93
}
```
Every claim is tied to a tool result. The memory limit and the timeout are never mentioned — they aren't in the evidence for *this* failure, so they don't enter the reasoning. The "diagnose ONE root cause" instruction kills the distractors here, before any fix exists.

**Node 3 · Remediation** → repo write-PR only, blast radius **12 lines max**, `approval: required`
- Reads the *actual* file with `read_repo_file` (no guessed path, no reconstruction from memory).
- Changes exactly one value. `ProposedPatch`:
```json
{ "files_changed": ["apps/checkout-svc/deployment.yaml"],
  "rationale": "checkout-svc has been crashlooping since r42 (commit 9f2c1ab). That revision set PAYMENT_ENDPOINT to 'htps://…' — a typo in the URL scheme — and the service exits 1 with 'unsupported URL scheme \"htps\"'. This restores the scheme to https and changes nothing else. After merge, watch replicas_ready return to 3/3 and error_rate fall below 0.05." }
```
The PR body is written *for the reviewer*: what broke, the evidence, what changed, what to watch. The 12-line cap makes the "modernize the image" failure structurally impossible — that patch would be refused at the write path.

**Node 4 · Human Review** → the human merges the one-line PR. The workflow was *halted* here (`awaiting_merge`) until they did.

**Node 5 · Verification** → post-merge, reads status + metrics, confirms `replicas_ready` 3/3 and `error_rate` < 0.05, closes the incident. Had it not recovered, it would have opened a revert PR rather than declaring victory.

---

## Scoring: same incident, both approaches

| Dimension | Single prompt | Warden Flow |
|-----------|:---:|:---:|
| Identifies the real root cause | Sometimes (variance) | **Yes, with cited evidence** |
| Fix scoped to the root cause | ✗ 3–4 collateral edits | **✓ one value** |
| Lines changed | whole file rewritten | **1** |
| Every claim traceable to evidence | ✗ none cited | **✓ 3 sources cited** |
| Calibrated confidence | ✗ uniform certainty | **✓ 0.93, and would lower it** |
| Hallucination guardrails (path / file reconstruction) | ✗ rewrites from memory | **✓ reads real file, capped diff** |
| Can it silently break prod? | ✗ yes (image swap, memory, probe) | **✓ blast radius refuses it** |
| Reviewer decision time | minutes (re-read everything) | **~30s (one line + rationale)** |
| Human approval gate | none | **✓ required before anything applies** |
| Verifies the fix actually worked | ✗ no | **✓ independent post-merge check** |
| Approx. token cost | one large call | ~5 smaller calls, tightly budgeted per node |

The workflow uses *more* model calls and is still safer and cheaper-per-node, because each node is capped and does one thing. The single prompt is one cheap call whose *expected cost* includes a chance of an outage.

---

## Reproduce it live

Both sides are runnable, so this comparison isn't a claim — it's a test.

**Warden Flow (real Gemini):**
```bash
python -m warden.agents.demo --live          # triage → diagnose → propose PR
python -m warden.agents.demo --verify-only   # after you merge the PR
```

**The single-prompt baseline:** paste the exact prompt in *Approach A* (logs + manifest + deploys) into the same model, once, and compare its `deployment.yaml` against the one-line PR. Run it five times to see the variance — how often it over-edits, and how often it misses the typo entirely.

The structure is the prompt engineering. The workflow doesn't ask the model to be more careful; it removes the room to be careless.
