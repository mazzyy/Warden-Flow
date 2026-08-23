# Warden — Agile Delivery Plan

**Project:** Warden — a governed remediation fleet
**Event:** All Things Agentic Hackathon · Category: **Fortified Enterprise Fleet**
**Team:** solo · **Capacity:** ~40h · **Window:** Thu 20 Aug → Sun 30 Aug 2026
**Hard deadline:** 31 Aug 17:00 PDT = **01 Sep 02:00 CEST**. Target submit **Sun 30 Aug**. Mon 31 Aug is buffer, not build time.

---

## Status — Thu 20 Aug, 23:00 CEST

**50% of MUST scope complete. ~24.5h remaining against 12 days.**

The honest framing: **the code is written and tested; nothing is deployed.** Everything below that's done runs offline against a fake estate — no cluster, no Gemini call, no Cloud Run. That's why it went fast, and it's why the remaining half won't.

**Done (19 stories, ~29.75h):** repo scaffold · Firestore schemas and store · agent registry · **policy proxy and enforcement** · audit log · budget ledger · EstateAdapter + AksAdapter · Triage, Diagnostician, Remediator · read-only tools · GitHub client · fixtures · both failure injections · the `estate-gitops` repo · plus two stories that weren't in the plan — the policy probe (W-108) and the preflight doctor (W-109).

**Remaining MUST:** Devpost draft (W-001) · cloud setup (W-002) · walking skeleton deploy (W-005) · AKS cluster (W-201) · alert bridge (W-205) · fleet health (W-107) · dashboard (W-601–603) · the entire submission package (W-701–709, 11h).

**W-004 is closed** — no longer at Siemens, so the IP question resolved itself. Confidentiality obligations survive, so the clean-room rule still holds for the video and blog.

**The one thing blocking everything cloud-side:** `gcloud billing projects describe gen-lang-client-0473437618`. Until that's confirmed, W-005, W-107, W-205 and all of Sprint 3's deployment are stuck.

---

## 0. How to use this document

Sections 1–4 are the *what and why* — read once, then leave alone. Section 5 is the backlog and Section 6 is the sprint plan; those two are your daily working surface. Section 9 is the cut list — you will need it, and the point of writing it now is that you decide the cuts while calm rather than at 1am on the 29th.

Story IDs (`W-xxx`) are stable. Use them in commit messages (`W-103: deny out-of-scope tool calls`) so the git log doubles as your burndown.

---

## 1. Vision and success criteria

### Product vision

> Warden is a governed fleet of autonomous SRE agents that watch a live cloud estate, diagnose failures, and land the fix as a reviewed GitOps pull request — with every action bounded by a versioned policy manifest, a token budget, and an append-only audit trail.

### The load-bearing idea

**No agent holds production write credentials. Their only write primitive is opening a pull request.**

Everything else in this plan exists to make that sentence demonstrably true on camera. If a design decision doesn't serve it, it's a candidate for the cut list.

### Success criteria, mapped to the judging rubric

| Rubric | Weight | What "done" means here | Evidence |
|---|---|---|---|
| Innovation & Operational Utility | 40% | An injected production failure is triaged, diagnosed and fixed with zero human input up to the merge button | Hero demo, scene 1 |
| Architectural Discipline & Tech Stack | 30% | Tool isolation is real and enforced, not documented. An out-of-scope call is provably denied | Denial scene + audit log |
| Demo & Production Readiness | 30% | Unedited live run, clean README, reproducible from a fresh clone | Video + repo |
| Bonus | up to 1.0 | Blog, social, Gemma routing | §5 E8 |

**Definition of Success (project level):** a judge who watches four minutes and clones the repo can restate the load-bearing idea in their own words, and reproduce the demo.

---

## 2. Architecture decisions

Short ADRs. Each is a decision you can point at when you're tempted to redesign at 2am.

### ADR-001 · Agents propose, humans merge
**Decision:** No agent gets cluster or cloud write credentials. The Remediator's only mutating tool is `propose_patch`, which opens a PR against a separate GitOps repo. No agent has merge rights.
**Why:** It's the honest answer to "would you let this near production", it's a genuine architectural constraint rather than a prompt instruction, and it converts partial correctness from a demo failure into a normal review cycle.
**Consequence:** The demo requires a merge action. Do it live on camera — it reads as deliberate governance, not a limitation.

### ADR-002 · Policy enforcement at a single proxy, not in prompts
**Decision:** Agents never call tools directly. Every call goes through one Policy Tool Proxy that loads the caller's manifest, checks scopes and blast radius, debits the budget, writes the audit record, and only then dispatches.
**Why:** Prompt-level guardrails are unfalsifiable. A choke point is testable, demoable, and is the thing the 30% architecture score is actually asking for.
**Consequence:** One extra hop on every tool call. Worth it. It is also the single most reusable artifact in the repo.

### ADR-003 · Agents are declared, not coded
**Decision:** Each agent is a YAML manifest — model, tools, scopes, blast radius, budget, approval mode, circuit breaker — versioned in git and loaded into a Firestore registry.
**Why:** GitOps for agents. It makes "fleet" mean something structural rather than "four agents in a chain", and it's a shape you already know cold from Kubernetes.
**Consequence:** A manifest loader and a schema to maintain. Budget 1.5h.

### ADR-004 · Estate on Azure, fleet on Google Cloud ← *the credits decision*
**Decision:** The **agent fleet, control plane, dashboard and all AI** run on Google Cloud (Cloud Run, Pub/Sub, Firestore, Secret Manager, Cloud Trace, Vertex AI). The **managed estate** — the AKS cluster and the demo workload the agents watch — runs on Azure, paid from your €1000.
**Why:** The hackathon requires Gemini 3.5+, a Google agent framework, and at least one Google Cloud infra service. All three are satisfied several times over by the fleet side. Meanwhile the only meaningfully expensive non-AI component is a Kubernetes cluster, and you have €1000 of Azure credit sitting idle against $10 of Google credit. Spending Azure money on compute preserves your entire Google balance for Gemini tokens, which is the one cost that *cannot* move.
**Second-order benefit:** a heterogeneous estate is a better enterprise story than a single-cloud one. Real fleets govern workloads they didn't provision. Say this out loud in the video — "the agents run on Google Cloud, the estate can be anywhere" — and it reads as design, not thrift.
**Risk:** a judge perceiving this as "not really a Google Cloud project."
**Mitigation:** every agent, every model call, and the entire control plane is Google. Show the Google Cloud console explicitly in the deployment-proof segment of the video (it's a stated requirement anyway). The Azure side is a *managed resource*, not a dependency of the product.

### ADR-005 · The estate sits behind an adapter
**Decision:** All estate access goes through one interface. `AksAdapter` now; `GkeAdapter` when the $150 lands.

```python
class EstateAdapter(Protocol):
    def list_workloads(self, scope: str) -> list[Workload]: ...
    def describe_workload(self, ref: WorkloadRef) -> WorkloadDetail: ...
    def get_workload_logs(self, ref: WorkloadRef, since: str, limit: int) -> list[LogLine]: ...
    def get_recent_deploys(self, ref: WorkloadRef, limit: int) -> list[Deploy]: ...
    def query_metrics(self, ref: WorkloadRef, metric: str, window: str) -> MetricSeries: ...
    def get_workload_status(self, ref: WorkloadRef) -> Status: ...
```

**Why:** This is the entire answer to "use Azure now, change later." Tool schemas, agent manifests, prompts and the proxy are all written against the interface, so they never learn which cloud they're on.
**Migration, when credits arrive:** add `GkeAdapter`, `terraform apply infra/gcp/gke`, flip `ESTATE_ADAPTER=gke`. Nothing else changes. Budget 2–3h, and it is entirely optional — the Azure estate is a perfectly valid submission.

### ADR-006 · Fixtures for development, live for the demo
**Decision:** Record real agent runs to JSON and replay them offline for all iteration. Call the live model only when validating a change to prompts or tools.
**Why:** With $10 of Google credit you cannot afford to run the fleet on every code change. This is a cost control that also makes tests deterministic.
**Hard constraint:** the *submitted video must show unedited live execution*. Fixtures are a development tool and must never appear in the demo. Keep them in `tests/fixtures/` and gate replay behind an env var that is off by default.

---

## 3. Environment and cost plan

### What runs where

| Layer | Cloud | Services | Paid from |
|---|---|---|---|
| Agent fleet | **Google** | Cloud Run (4 services) | free tier / $150 |
| Control plane | **Google** | Firestore, Secret Manager | free tier |
| Event bus | **Google** | Pub/Sub, Cloud Scheduler | free tier |
| Models | **Google** | Vertex AI — Gemini 3.5, Gemma | **$10 now, $150 pending** |
| Observability | **Google** | Cloud Trace | free tier |
| Dashboard | **Google** | Cloud Run | free tier |
| **Managed estate** | **Azure** | AKS (Free control plane) + 2× B2s nodes | **€1000** |
| GitOps repo | GitHub | 2 repos (`warden`, `estate-gitops`) | free |

### Cost forecast

**Azure — comfortable.** AKS control plane is free on the Free tier; you pay for nodes. ⚠️ **Corrected:** B-series VMs are *not supported for AKS system node pools*, so the original `Standard_B2s` plan would have failed at `az aks create`. Use `Standard_D2s_v5` — two nodes for eleven days is roughly **€58**, call it €80 with logs and egress. Against €1000 that's still noise, so don't micro-optimise and don't waste an hour on shutdown automation. `az aks stop` overnight halves it if you want.

**Google — tight until the $150 lands.** Cloud Run scales to zero, Firestore and Pub/Sub free tiers cover hackathon volumes comfortably, Secret Manager is cents. **Gemini tokens are effectively your entire Google spend.** Four disciplines, in order of impact:

1. **Fixtures (ADR-006).** Biggest saver by a wide margin. Record once, replay hundreds of times.
2. **Flash for all iteration.** Reserve the top tier for the Diagnostician and only on real runs.
3. **Cap tokens in the manifests.** `budget.maxTokensPerRun: 120000` is enforced by the proxy, so a runaway loop costs you a denial rather than your balance.
4. **Set a Google billing alert at $5** on day one, before you write any agent code.

There's a nice line in this for the video and the blog: *the budget ledger wasn't a demo feature, it's how the whole thing got built on ten dollars of credit.* That's a true story about cost governance in agent fleets, and it's more persuasive than any architecture slide.

### Secrets

Azure cluster access is a **read-only** Kubernetes ServiceAccount token, stored in **Google Secret Manager**, injected into Cloud Run. Never a cluster-admin kubeconfig — the read-only binding is part of the ADR-001 story, so make it real and mention it on camera.

---

## 4. Epics

| ID | Epic | Sprint | Est |
|---|---|---|---|
| **E1** | Foundations & walking skeleton | 0 | 4.75h |
| **E2** | Control plane — registry, policy, audit, budget, health | 1 | 8.5h |
| **E3** | Managed estate & failure injection | 1 | 6h |
| **E4** | Perception agents — Triage, Diagnostician | 1–2 | 7h |
| **E5** | Action agents — Remediator, Verifier | 2 | 4.5h |
| **E6** | Memory & observability | 2 | 4h |
| **E7** | Dashboard & kill switch | 2 | 5h |
| **E8** | Submission package | 3 | 11h |
| **E9** | Stretch — Drift agent and beyond | backlog | — |

---

## 5. Product backlog

Priority is MoSCoW. Estimates are hours, because for an eleven-day solo push abstract points buy you nothing.

### E1 · Foundations & walking skeleton

**W-001 · Devpost registration and draft submission** — MUST — 0.5h
Register, select Fortified Enterprise Fleet, save a draft submission with placeholder text.
*AC:* draft exists and is editable · category selected · reminder set for 30 Aug.
*Why now:* removes all last-hour submission risk for thirty minutes of work.

**W-002 · Cloud accounts and guardrails** — MUST — 1h
Follow the setup runbook (`warden-cloud-setup.md`) §1–§10. Budget guards first, before any API that can spend.
*AC:* `gcloud` and `az` both authenticated · **$5 GCP budget with three thresholds, and a test alert email actually received** · Azure budget set · a trivial Vertex call succeeds and you can read `usageMetadata` off the response.
*Two traps the runbook covers:* `--threshold-rule=percent=` takes a fraction (`0.50`, not `50`) — get this wrong and the alert never fires. And the Firestore location is **permanent**, so read §3 before running it.

**W-003 · Repo scaffold** — MUST — 0.5h
Two repos: `warden` and `estate-gitops`. Python project, ruff + pytest, README skeleton, Apache-2.0.
*AC:* first commit dated after 3 Aug (rules requirement) · CI runs lint on push.

**W-004 · Employer IP check** — MUST — 0.25h
Read your Siemens contract for side-project and adjacent-domain clauses before writing code.
*AC:* a decision recorded in `docs/adr/`. If ambiguous, ask before you build, not after you win.

**W-005 · SPIKE: walking skeleton** — MUST — 2.5h
One thread through every layer: publish to Pub/Sub → ADK agent on Cloud Run consumes → writes a document to Firestore.
*AC:* a message published from your laptop appears as a Firestore document within 30s, produced by a deployed ADK agent.
*Timebox:* 2.5h hard. If ADK deployment is fighting you at 2.5h, post in the Devpost Discord and continue with a plain Cloud Run service; swap in ADK later.
*This is the highest-risk unknown in the project. Killing it on day two is the single most valuable thing in Sprint 0.*

### E2 · Control plane

**W-101 · Firestore schemas and repository layer** — MUST — 2h
Collections per Appendix B, with a thin typed access layer.
*AC:* create/read round-trips for `incidents`, `runs`, `audit` · no raw Firestore calls outside the repository module.

**W-102 · Agent manifest spec and loader** — MUST — 1.5h
YAML → validated model → Firestore registry. Reject unknown tools at load time.
*AC:* `warden registry sync` loads four manifests · a manifest referencing an unregistered tool fails loudly with the tool name.

**W-103 · Policy tool proxy** — MUST — 2.5h
Single dispatch point. Loads manifest, checks tool allow-list, scopes and blast radius, then dispatches or denies.
*AC:* Remediator calling `describe_workload` → allowed · Remediator calling `delete_workload` → denied with a human-readable reason naming the missing scope · **a unit test asserts the denial**.
*This story is the project. If everything else is late, this still has to be excellent.*

**W-104 · Audit log** — MUST — 1h
Append-only write on every call, allowed or denied, keyed by incident and run.
*AC:* a full incident produces an ordered, queryable audit trail · denials record the reason · nothing in the system can write a tool call without an audit record (enforce in the proxy, not by convention).

**W-105 · Budget ledger** — SHOULD — 1.5h
Per-run token and tool-call caps, debited by the proxy, enforced before dispatch.
*AC:* a run exceeding `maxToolCalls` is halted and marked `budget_exceeded` rather than crashing.

**W-106 · Circuit breaker** — COULD — 1h
Open after N consecutive failures, cool down, half-open retry.

**W-107 · Fleet health and credential monitor** — MUST — 1.5h
`GET /healthz` probing GitHub token, estate reachability, Vertex auth, budget burn and Firestore. Live probes, not expiry parsing — probing catches revocation, rotation, quota exhaustion and expiry at once. 200 healthy / 503 degraded, behind a Cloud Monitoring uptime check that emails you.
*AC:* revoking the GitHub token turns `/healthz` red within one check interval · budget burn reads real `usageMetadata.totalTokenCount` off Gemini responses rather than estimating · the alert email actually arrives (test it).
*Dual purpose:* the same uptime check guards the demo URL through the **Sept 1 – Oct 1 judging window** — the failure mode most likely to quietly cost you a prize, because you won't be watching. See the setup runbook §11.

### E3 · Managed estate

**W-201 · AKS cluster and demo workload** — MUST — 2h
Terraform in `infra/azure/`. AKS Free tier, 2× B2s. Deploy `checkout-svc` from `estate-gitops`.
*AC:* `kubectl get pods` green · workload reachable · manifests live in `estate-gitops`, not in the app repo.

**W-202 · EstateAdapter + AksAdapter** — MUST — 2h
Per ADR-005. Read-only ServiceAccount, token in Google Secret Manager.
*AC:* all six interface methods return real data from Cloud Run · **the SA token cannot mutate the cluster — prove it with a failing `kubectl delete` using that token, and keep the terminal output for the video.**

**W-203 · Failure injection: bad config** — MUST — 1h
Script that commits an env var typo, triggering a crashloop. This is your hero scene.
*AC:* one command breaks the service reproducibly · one command restores it · runs cleanly five times in a row.

**W-204 · Failure injection: OOMKill** — SHOULD — 0.5h

**W-205 · Alert bridge** — MUST — 1h
Cluster health signal → Pub/Sub `warden.events`. A polling watcher is fine and is less work than wiring Azure Monitor to GCP; don't gold-plate this.
*AC:* breaking the service publishes a well-formed event within 60s.

### E4 · Perception agents

**W-301 · Triage agent** — MUST — 2h
Consume events, dedupe against recent incidents, score severity, decide whether to escalate.
*AC:* duplicate alerts within a window collapse into one incident · a low-severity event is closed without escalating · the decision and its reasoning are persisted.

**W-302 · Read-only tool implementations** — MUST — 2h
`get_workload_logs`, `describe_workload`, `recent_deploys`, `query_metrics` — all via EstateAdapter, all registered with the proxy.
*AC:* each callable through the proxy · each denied when the caller's manifest lacks the scope.

**W-303 · Diagnostician agent** — MUST — 3h
Read-only investigation producing a hypothesis with an explicit evidence chain.
*AC:* for the bad-config injection, correctly identifies the offending env var and cites the log lines and the deploy that introduced it · **runs clean three times consecutively** (this is a demo-reliability gate, not a correctness one).

**W-304 · Fixture recorder and replayer** — SHOULD — 1.5h
Per ADR-006. Off by default.
*Do this early in Sprint 1 if the $150 hasn't landed — it pays for itself within a day.*

### E5 · Action agents

**W-401 · GitHub integration and `propose_patch`** — MUST — 2h
App or fine-grained PAT scoped to `estate-gitops` only. Branch, commit, open PR.
*AC:* tool opens a real PR with a title, body and diff · **the token cannot push to `main` — verify it.**
*Schedule note: this is mechanical plumbing with no reasoning required. Do it on a tired evening and save your fresh hours for W-303 and W-402.*

**W-402 · Remediator agent** — MUST — 2.5h
Turn a diagnosis into a minimal patch plus a rationale.
*AC:* bad-config incident produces a PR reverting exactly the offending value · PR body explains the reasoning and links the incident ID · touches no more than `blastRadius.maxFilesPerPatch` files.

**W-403 · Verifier agent** — SHOULD — 2h
Post-merge SLO watch, then close the incident or escalate.

**W-404 · Auto-revert on failed verification** — COULD — 1.5h

### E6 · Memory & observability

**W-501 · OpenTelemetry → Cloud Trace** — SHOULD — 2h
One trace tree per incident, spanning all agents and proxy calls.
*AC:* a single trace shows the full incident. Screenshot it for the submission — it's strong architecture evidence for very little work.

**W-502 · Memory Bank writes** — SHOULD — 1.5h
Persist incident resolutions. *The 27 Aug webinar covers exactly this — watch it the same evening you build it.*

**W-503 · `recall_similar_incidents`** — SHOULD — 1.5h
Triage dedupe backed by memory. This is what makes the fleet look like it has been running for months rather than four days.

### E7 · Dashboard & kill switch

**W-601 · Fleet and incident views** — MUST — 2h
*AC:* agents with their manifests and budgets · incidents with status · loads in under 2s cold.

**W-602 · Run detail view** — MUST — 2h
Timeline of tool calls with allow/deny badges and reasons.
*AC:* **the denial is visually obvious** — this screen is the Best Architectural Design pitch, so spend the polish here rather than on the fleet list.

**W-603 · Kill switch** — MUST — 1h
Sets `fleet/state.killSwitch`; the proxy refuses all dispatch while set.
*AC:* toggling mid-incident halts the run and records why.

**W-604 · Seed data** — SHOULD — 0.5h
Three resolved incidents so a judge doesn't land on an empty page.

### E8 · Submission package

**W-701 · Feature freeze and hardening** — MUST — 2h · *Fri 28 Aug, non-negotiable date*
**W-702 · README with tested spin-up** — MUST — 2h — *AC: you follow your own README from a fresh clone in a clean directory and it works. Actually do this; don't assume.*
**W-703 · Final architecture diagram** — MUST — 1h
**W-704 · Video script and three dry runs** — MUST — 2h
**W-705 · Record and cut the video** — MUST — 3h — *≤4 min, unedited live execution, Google Cloud console proof, English subtitles*
**W-706 · Blog post** — SHOULD — 1.5h — *bonus 0.2 · angle: "I gave an AI agent zero production credentials and it fixed the outage anyway"*
**W-707 · Social post** — SHOULD — 0.25h — *bonus 0.2 · `#AllThingsAgenticHackathon`*
**W-708 · Gemma triage classifier** — SHOULD — 1.5h — *bonus up to 0.6, and a genuine cost-architecture improvement*
**W-709 · Finalise Devpost submission** — MUST — 1h — *repo access for `testing@devpost.com` and `cloudhackathons@google.com` if private*

### E9 · Stretch — do not start before Sprint 3 is safe

**W-801 · Drift agent** — 6h — the Terraform/ClickOps idea, on Cloud Scheduler: compare live state to IaC, open a PR codifying the drift.
**W-802 · Third failure injection** — 1h
**W-803 · Multi-tenant estate** — WON'T
**W-804 · Approval-gate UI** — COULD

---

## 6. Sprint plan

### Sprint 0 · Foundations — Thu 20 – Fri 21 Aug · 5h
**Goal:** an event travels from your laptop to Firestore through a deployed agent.

| Day | Hours | Stories |
|---|---|---|
| Thu 20 | 2 | W-001, W-002, W-004, W-003 |
| Fri 21 | 3 | W-005 (spike, timeboxed 2.5h) |

**Exit gate:** walking skeleton green. If it isn't, Saturday starts by finishing it and Sprint 1 loses 2h — adjust immediately rather than hoping.

### Sprint 1 · Spine and perception — Sat 22 – Sun 23 Aug · 16h
**Goal:** an injected failure becomes an audited, triaged, diagnosed incident.

| Day | Hours | Stories |
|---|---|---|
| Sat 22 | 8 | W-201 (2) · W-205 (1) · W-101 (2) · W-102 (1.5) · W-103 start (1.5) |
| Sun 23 | 8 | W-103 finish (1) · W-104 (1) · W-202 (2) · W-302 (2) · W-203 (1) · W-304 (1) |

**Exit gate (Sun evening):** break the service → an incident exists in Firestore with a complete audit trail. **Record a 30-second screen clip.** Do this at every sprint boundary and you'll arrive at Saturday's video shoot with usable b-roll already in hand.

*Plan eight hours, not ten. You do not get ten productive hours in a day, and pretending otherwise is how the 29th becomes a disaster.*

### Sprint 2 · Closing the loop — Mon 24 – Thu 27 Aug · 10h
**Goal:** an alert produces a real pull request, with no human in the loop.

| Day | Hours | Stories |
|---|---|---|
| Mon 24 | 2.5 | W-401 (2) · W-301 start (0.5) — *mechanical work on a post-work evening* |
| Tue 25 | 2.5 | W-301 finish (1.5) · W-303 start (1) |
| Wed 26 | 2.5 | W-303 finish (2) · W-402 start (0.5) |
| Thu 27 | 2.5 | W-402 finish (2) · Memory Bank webinar |

**Exit gate (Thu 27, ~22:00) — the decision point of the whole project:** does an injected failure produce a correct PR end to end?

- **Yes** → Sprint 3 proceeds as written, and W-601/602/603 land Friday alongside hardening.
- **No** → **execute the cut list (§9) immediately.** Do not spend Friday debugging and hope to catch up on Saturday; Saturday belongs to the video and cannot be borrowed against.

### Sprint 3 · Ship — Fri 28 – Sun 30 Aug · 15h
**Goal:** submitted, a day early.

| Day | Hours | Stories |
|---|---|---|
| Fri 28 | 3 | **Feature freeze.** W-701 · W-107 · W-601/602/603 if not already done · W-604 |
| Sat 29 | 8 | W-704 (2) · W-705 (3) · W-702 (2) · W-706 (1) |
| Sun 30 | 4 | W-703 (1) · W-707 · W-708 if time · **W-709 — submit** |

**Feature freeze on Friday 28th is the most important date in this plan.** Every hackathon post-mortem ever written says the same thing: the video takes three to four times longer than expected, and the people who lose are the ones still writing features on the final Saturday.

---

## 7. Definition of Ready / Definition of Done

**Ready** — a story can be started when: acceptance criteria are written; its dependencies are done; it's estimated at ≤3h (split it if not); and you know which cloud it touches.

**Done — per story:** AC met · runs from a clean clone · unit test where behaviour is non-obvious (proxy denials always) · no secrets in git · commit references the story ID · board updated.

**Done — project:** all MUSTs complete or explicitly cut with a reason recorded · video published and under 4 minutes · README verified from a fresh clone in a clean directory · architecture diagram current · Devpost submitted · repo access granted if private · billing alerts live.

---

## 8. Risk register

| # | Risk | L | I | Mitigation | Trigger |
|---|---|---|---|---|---|
| R1 | Google credits don't arrive | M | M | Azure estate (ADR-004), fixtures (ADR-006), Flash-first, $5 billing alert | Not landed by Mon 24 → fixtures become mandatory, not optional |
| R2 | ADK learning curve blows the estimate | M | H | Sprint 0 spike, hard-timeboxed at 2.5h; Discord for support | Spike incomplete Fri night → fall back to plain Cloud Run, add ADK later |
| R3 | Cross-cloud auth friction | M | M | Read-only SA token in Secret Manager, public API server, no VPN or peering | >2h spent → run the estate as k3d on a single Azure VM instead |
| R4 | Demo fails on camera (rules forbid editing around it) | M | **H** | Three dry runs; W-203 must pass 5 consecutive clean runs before Sat | Any dry-run failure → fix or simplify the scene, don't hope |
| R5 | Scope creep | **H** | H | Cut list §9; Thu 27 gate | Any new idea after Fri 28 goes to E9, no exceptions |
| R6 | Evening capacity overestimated (work + thesis) | **H** | M | Evenings planned at 2.5h, not 4h | Two consecutive missed evenings → cut immediately |
| R7 | Employer IP conflict | L | **Critical** | W-004 on day one; clean-room implementation; nothing internal referenced | Any ambiguity → ask before building further |
| R8 | Video overruns 4 min | M | M | Script to time; only the first 4 min are evaluated | Dry run >4:00 → cut the architecture segment, not the live run |
| R9 | Judge reads Azure as non-Google | L | M | All AI and control plane on Google; console shown explicitly in video | — |

---

## 9. Scope reconciliation and the cut list

**Be honest about the arithmetic.** MUST stories total **~47h against a 40h capacity** — an 18% overcommit, up from 12% now that W-107 is in. It earns its place: with a $10 balance, an unnoticed budget burn or a dead credential is a project-ending event, and the same endpoint guards your demo URL through judging. But it does mean the cut list is no longer a contingency you might need — **plan on executing at least items 1 and 2.** Close the rest by finding one extra half-day; Wednesday afternoon off is the cheapest place to get it.

**Cut in this order, at the Thursday 27th gate:**

1. **Dashboard becomes read-only** — drop the kill-switch UI, trigger it via API on camera instead. *−1.5h, costs almost nothing.*
2. **Diagnostician drops to two tools** — logs and recent deploys are enough for the bad-config scene. *−1h.*
3. **One failure injection only.** *−0.5h.*
4. **Drop the Verifier (W-403/404).** The human merges, the service recovers, you narrate it. *−3.5h, and the demo still closes the loop.*
5. **Drop the EstateAdapter abstraction**, code straight against the k8s client. *−1h, but you accept the migration debt — take this one last.*
6. **Drop the blog post.** *−1.5h, costs 0.2 bonus. Cut this before you cut anything that appears on camera.*

**Never cut, under any circumstances:** the policy proxy and its denial (W-103/104), the video (W-705), the README (W-702), the architecture diagram (W-703), the Devpost submission (W-709). The last four are pass/fail in stage one of judging — a brilliant project that fails stage one scores zero.

---

## 10. Working rhythm (solo scrum)

- **Start of session, 10 min:** pull the top story off the board, re-read its AC, write the failing test if there is one.
- **End of session, 10 min:** update the board, commit with the story ID, write one line on what's blocked. Never end a session on a broken build — future-you at 22:00 on a Tuesday will not thank you.
- **Sprint boundary:** demo to yourself and **record a 30-second clip.** By the 29th you'll have four clips of real progress footage.
- **Thu 27, 22:00:** the gate. Be ruthless. Deciding to cut is a win, not a failure.

---

## 11. Submission checklist

- [ ] Category: **Fortified Enterprise Fleet**
- [ ] Hosted dashboard URL, seeded (soft requirement — the *video* is the hard deployment proof)
- [ ] Text description: features, technologies, data sources, learnings
- [ ] Repo with spin-up instructions, verified from a fresh clone
- [ ] If private: access for `testing@devpost.com` and `cloudhackathons@google.com`
- [ ] Architecture diagram
- [ ] Video ≤4 min · unedited live execution · Google Cloud console proof · English subtitles · public on YouTube or Vimeo
- [ ] Pre-existing code disclosed (should be: none)
- [ ] Bonus: blog · social `#AllThingsAgenticHackathon` · Gemma documented in the description
- [ ] Billing alerts live on both clouds

---

## Appendix A · Repository layout

```
warden/                          # main repo
├── README.md                    # spin-up instructions — judged
├── docs/
│   ├── architecture.md
│   ├── architecture.svg
│   └── adr/                     # ADR-001 … ADR-006
├── manifests/agents/            # the registry's source of truth
│   ├── triage.yaml
│   ├── diagnostician.yaml
│   ├── remediator.yaml
│   └── verifier.yaml
├── warden/
│   ├── agents/                  # ADK agent definitions
│   ├── proxy/                   # policy tool proxy  ← the crown jewel
│   ├── control_plane/           # registry · policy · budget · audit
│   ├── estate/                  # EstateAdapter · AksAdapter · GkeAdapter
│   ├── tools/                   # implementations, reachable only via proxy
│   └── dashboard/
├── infra/
│   ├── gcp/                     # Cloud Run · Pub/Sub · Firestore · Secret Manager
│   └── azure/                   # AKS · node pool
├── scripts/
│   ├── inject_bad_config.sh
│   ├── inject_oom.sh
│   └── seed_demo_data.py
└── tests/
    └── fixtures/                # recorded runs — dev only, never in the demo

estate-gitops/                   # SEPARATE repo — what agents open PRs against
├── apps/checkout-svc/
└── terraform/
```

The estate must be a **separate repository**. The Remediator's token is scoped to it and nothing else, which is what makes the credential story provable rather than asserted.

## Appendix B · Firestore schemas

```
agents/{name}       manifest, version, enabled, updatedAt
incidents/{id}      source, signature, severity, status, workloadRef,
                    openedAt, closedAt, memoryRefs[]
runs/{id}           incidentId, agent, model, startedAt, endedAt,
                    status, tokensUsed, toolCallCount, outcome
audit/{id}          runId, incidentId, agent, tool, argsRedacted,
                    decision(allow|deny), reason, latencyMs, ts
budgets/{runId}     tokensSpent, toolCalls, capTokens, capCalls
fleet/state         killSwitch(bool), drainedAt
```

## Appendix C · Proxy contract

```jsonc
// request
{ "runId": "...", "incidentId": "...", "agent": "remediator",
  "tool": "propose_patch", "args": { } }

// allow
{ "ok": true, "result": { } }

// deny
{ "ok": false, "decision": "deny",
  "reason": "tool 'delete_workload' not in manifest allow-list for agent 'remediator'",
  "auditId": "..." }
```

The deny reason is user-facing copy. It appears on screen in the demo — write it like it matters.

## Appendix D · Key links

Rules https://allthingsagentichackathon.devpost.com/rules · Resources https://allthingsagentichackathon.devpost.com/resources · FAQ https://allthingsagentichackathon.devpost.com/details/faqs
ADK https://google.github.io/adk-docs · ADK Python https://github.com/google/adk-python · Cloud Run deploy https://google.github.io/adk-docs/deploy/cloud-run/
Memory Bank https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank · Agent Runtime https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime
Discord https://discord.gg/HP4BhW3hnp
**Webinar Thu 27 Aug** — Architecting Agent Memory (session state, vector search, managed cloud memory). Last one on the schedule, and it lands the same evening as W-502.
