# Warden — All Things Agentic Hackathon build plan

**Category:** Fortified Enterprise Fleet · **Entry:** solo · **Budget:** ~40h across 11 days
**Deadline:** Aug 31 2026, 5:00pm PDT = **02:00 CEST on Sept 1** (Berlin). Target submit: **Sun Aug 30.**

---

## 1. The decision: why this, and why not the Terraform agent

You asked about the autonomous SRE fleet and the ClickOps→Terraform agent. Build the fleet. Here's the honest reasoning.

The Terraform idea has the better one-sentence pitch — you lived it at PUMA and cut provisioning time 90%, so you can speak to it with real authority. But the engineering underneath is a trap on an 11-day clock. Generating HCL that reverse-engineers live cloud state and then produces a *clean* `terraform plan` diff after `import` is a research-grade problem. Resource attribute coverage is uneven, provider defaults leak into diffs, and state reconciliation fails in ways that are tedious rather than interesting. If the plan output isn't clean, the demo dies on camera — and the video is 30% of your score with a hard "unedited, live execution" requirement.

The SRE fleet inverts that risk. Its unit of action is **a pull request**, not a mutation. A PR that's 80% right is still a great demo, because a human reviewing an agent's proposed diff is the *intended* workflow, not a failure mode. The bar for "good enough" drops enormously, and the thing you're demoing — an agent that removes a 3am page — is more visceral than a config refactor.

It also sits directly on your CV. GitOps tooling on Kubernetes, secure container image workflows, CI/CD stages, runbook creation at Siemens Healthineers; RBAC and data-security controls at Asaan Recovery; Terraform modules at PUMA. Most hackathon entrants will ship a chatbot with tools bolted on. Almost nobody in that field can build a real control plane with policy enforcement and an audit trail, because almost nobody has done platform engineering. That's your moat, and "Fortified Enterprise Fleet" is the category that asks for exactly it — the brief names agent registries, runtime execution, memory, security governance, and observability.

**And you don't lose the Terraform idea.** It becomes one scheduled agent inside the fleet — the Drift agent — that compares live cloud state to the IaC in the repo and opens a PR codifying whatever someone ClickOps'd in the console. Scoped as a stretch goal (§7), it's a 30-second scene in your video instead of an 11-day gamble.

**Prizes you're eligible for with one submission:** Fortified Enterprise Fleet ($20k), Grand Prize ($50k), Best Architectural Design ($5k × 2), Individual/Hobbyist ($10k × 2, and you're solo so this is automatic), Honorable Mention ($2k × 5). Only one prize per project, but you're in five pools. Startup Excellence is out — it needs an incorporated org and corporate email.

---

## 2. The pitch

> **Warden** is a governed fleet of autonomous SRE agents that watch a live cloud estate, diagnose failures and configuration drift, and land the fix as a reviewed GitOps pull request — with every action bounded by a versioned policy manifest, a token budget, and an append-only audit trail.

The single design decision that carries the whole submission:

> **No agent in the fleet holds production write credentials. Their only write primitive is opening a pull request.**

Say that sentence in the first 30 seconds of your video. It reframes the entire "can we trust agents in production" problem, it's architecturally load-bearing rather than decorative, and it's the kind of thing a judge repeats to another judge.

---

## 3. Architecture

### Signal → decision → proposal → verification

```
Cloud Monitoring alert ─┐
Cloud Scheduler (cron)  ├─→ Pub/Sub `warden.events` ─→ Triage ─→ Diagnostician ─→ Remediator ─→ Verifier
GitHub webhook          ─┘                                  │           │              │            │
                                                            └───────────┴──────────────┴────────────┘
                                                                          ↓
                                                              Policy Tool Proxy  ← every tool call
                                                                          ↓
                                                        Managed estate (read) · GitOps repo (write)
```

### The four agents

| Agent | Model tier | Tools | Job |
|---|---|---|---|
| **Triage** | Gemini 3.5 Flash (or Gemma for the classifier — see §6) | `recall_similar_incidents`, `get_alert_context` | Dedupe against past incidents, assign severity, decide whether this is worth waking the fleet for. Most alerts die here — that's the point. |
| **Diagnostician** | Strongest Gemini 3.5 tier available | `get_workload_logs`, `describe_workload`, `recent_deploys`, `query_metrics` — **all read-only** | Produce a hypothesis with an explicit evidence chain. This is where the model reasoning actually earns its keep. |
| **Remediator** | Strongest Gemini 3.5 tier available | `read_repo_file`, `propose_patch` | Write the fix into the GitOps repo as a PR. Cannot touch the cluster. Cannot merge. |
| **Verifier** | Gemini 3.5 Flash | `query_metrics`, `get_workload_status`, `request_revert` | After the PR merges and syncs, watch SLOs for N minutes. Close the incident, or open a revert PR. |

Four agents is the right number. Three feels thin for a "fleet"; six means none of them work by Aug 30.

### The control plane (this is the differentiator)

Not agents — infrastructure. This is the part that makes it a *fleet* rather than a chain.

**Agent manifests.** Every agent is declared in YAML that looks deliberately like a Kubernetes CRD, versioned in Git, loaded into a Firestore registry:

```yaml
apiVersion: warden.dev/v1
kind: Agent
metadata:
  name: remediator
spec:
  model: gemini-3.5-<tier>
  tools: [read_repo_file, propose_patch]
  scopes: ["repo:estate-gitops:write-pr", "cluster:demo:read"]
  blastRadius: { namespace: demo, maxFilesPerPatch: 3 }
  budget: { maxTokensPerRun: 120000, maxToolCalls: 25 }
  approval: required          # auto | required
  circuitBreaker: { failuresBeforeOpen: 3, cooldownSeconds: 900 }
```

You are, in effect, building GitOps for agents. Nobody else in that Devpost gallery is going to do this, and it is a direct, legible answer to the rubric's "system decoupling, state management, robust design, tool isolation."

**Policy tool proxy.** Agents never invoke tools directly. Every call is routed through one enforcement point that checks the caller's manifest, records the call to the audit log, and denies anything out of scope. It is a single choke point — easy to explain, easy to draw, easy to demo.

**Budget ledger.** Per-run token and tool-call caps, enforced by the proxy. Circuit breaker opens after repeated failures. The rubric explicitly names failure handling; most submissions will have nothing to point at here.

**Audit log.** Append-only Firestore collection. Every tool call, every denial, every model decision, every PR, keyed by incident ID.

**Kill switch.** One button in the dashboard that drains the fleet mid-incident. Show it working.

**Observability.** OpenTelemetry spans → Cloud Trace, so a single incident produces one trace tree spanning all four agents. Screenshot this for the submission.

### Requirement coverage

| Requirement | How |
|---|---|
| Gemini 3.5+ via Gemini API or Vertex AI | Vertex AI, mixed tiers by cost profile |
| ≥1 Google Agent Framework | **ADK (Python)** — your strongest language |
| ≥1 Google Cloud infra service | Cloud Run, Pub/Sub, Firestore, Cloud Scheduler, Secret Manager, Cloud Trace — six |
| Memory | Agent Platform **Memory Bank** for incident recall (there's a workshop on it Aug 27) |
| Hosted URL for judging | The dashboard on Cloud Run, seeded with past incidents |

---

## 4. The demo estate

A deliberately fragile service — call it `checkout-svc` — plus three scripted failure injections.

**Don't run GKE Autopilot for eleven days.** It will eat your $150 credit and your evenings. Run a k3d cluster on a small GCE VM (`e2-medium`): you get real kubectl semantics, which is your home turf, for a few euros. The agents themselves run on Cloud Run, which is what the judges will see and what the rules want proof of. If k3d fights you at all on day 3, drop it and make the estate pure Cloud Run services — the architecture doesn't change, only the `describe_workload` tool implementation does.

Three injections, built as scripts so you can re-run them on camera:

1. **Bad config rollout** — env var typo → crashloop. Full loop: triage → diagnose → PR reverting the value → merge → verify → resolved. *This is your hero scene.*
2. **Memory limit too low** — OOMKill → PR bumping limits → verify.
3. **The denial** — Remediator proposes deleting the workload; the policy proxy refuses because it's outside `blastRadius`; the audit log shows the denial with the reason. *This scene is your Best Architectural Design pitch.*

---

## 5. Day-by-day

| When | Hours | Work |
|---|---|---|
| **Thu Aug 20** (today) | 2 | Register on Devpost. **Submit the Cloud credit form now** (§8). Create GCP project, enable APIs, create the repo with today's first commit. **Create the Devpost submission as a draft today** — you can edit it until the deadline, and it removes all last-hour risk. |
| **Fri Aug 21** | 3 | Prove the pipe end-to-end before building anything on top of it: Pub/Sub message → ADK agent on Cloud Run → Firestore write. This is your biggest unknown; kill it on day two. |
| **Sat Aug 22** | 10 | Control plane. Firestore schemas (`agents`, `incidents`, `runs`, `audit`), manifest loader, **policy tool proxy with enforcement + audit writes**. Deploy the demo estate and confirm you can break it. |
| **Sun Aug 23** | 10 | Triage + Diagnostician with read-only tools. Success criterion: one real injected failure produces a correct hypothesis with evidence. |
| **Mon–Wed Aug 24–26** | 3 × 3 | Remediator (GitHub App or PAT → open PR), Verifier + auto-revert, wire the full loop. Get scene 1 running unattended. |
| **Thu Aug 27** | 3 | Dashboard: fleet view, live incidents, run traces, audit log, kill switch. Memory Bank webinar + wire incident recall into Triage. |
| **Fri Aug 28** | 3 | **Hard feature freeze.** Retries, budget caps, seed the hosted URL so judges don't land on an empty page. Write the blog post (§6). |
| **Sat Aug 29** | 8 | **Record the video.** Budget the whole day — it always takes 3–4× longer than expected. Script it, dry-run the break-fix three times, then record unedited. Test one-command spin-up from a clean clone. |
| **Sun Aug 30** | 5 | Final architecture diagram, social post, **submit**. |
| **Mon Aug 31** | — | Buffer only. Do not plan to build. |

---

## 6. Bonus points — do not skip these

Final scores run 1–6, where up to **1.0 is bonus**. That's ~17% of your ceiling, available for a few hours of non-engineering work. Ignoring it is the single most common way strong projects lose.

- **Published blog post** about the build — max 0.2. Write it Aug 28. You have a genuine angle: *"I gave an AI agent zero production credentials and it fixed the outage anyway."*
- **Social post** with `#AllThingsAgenticHackathon` — max 0.2. Five minutes on Aug 30.
- **Additional Google models** (Gemma, Veo, Lyria) — max 0.6 total. Use **Gemma** for the Triage classifier. This isn't points-chasing: routing high-volume, low-stakes alert classification to a small cheap model while reserving Gemini 3.5 for the hard diagnosis step is exactly the cost architecture a real fleet needs, and it gives you a genuine answer when a judge asks about per-incident cost.

That's 0.4 for roughly three hours, plus 0.6 for a decision that improves the architecture on its own merits.

---

## 7. Scope contract

**Build in this order. When you run out of time, cut from the bottom.**

1. Policy tool proxy + audit log ← *if only one thing exists, this*
2. Triage + Diagnostician, read-only, one working failure scene
3. Remediator opening a real PR
4. Dashboard with audit log and kill switch
5. Verifier + auto-revert
6. Memory Bank incident recall
7. — cut line at ~40h —
8. Drift agent (the Terraform idea, on Cloud Scheduler)
9. Second and third failure injections
10. Multi-tenant estate

**Non-negotiables regardless of what gets cut:** the video, the README spin-up instructions, the architecture diagram, a live hosted URL. Those are pass/fail in stage one of judging — a brilliant project that fails stage one scores zero.

---

## 8. Rules that will bite you

**Newly created work only.** Projects must be created during the submission period (Aug 3–31). New repo, first commit after Aug 3. You must disclose any pre-existing code you incorporate.

**Be careful about your day job.** This idea sits close to what you do at Siemens Healthineers. The rules bar submissions containing confidential or proprietary third-party information without authorization. Write everything from scratch, don't reference internal tooling, architecture, or runbooks, and if there's any ambiguity in your employment agreement about side projects in an adjacent domain, check it before you submit rather than after you win. This is the one item on this list that can cost you more than a prize.

**Credits deadline is earlier than you think.** The Cloud credit request form closes **Aug 28 at 12:00pm PT** — and credits take time to land. Submit it today: https://forms.gle/5PtXmw1dSbDnpYke9

**The hosted URL is softer than it looks — but keep it up anyway.** The FAQ says your app "doesn't need to be publicly accessible or deployed at the exact moment of submission or judging"; the hard requirement is that your *video* proves Google Cloud deployment (console screenshots or a live `.run` URL). So a lapsed URL won't disqualify you. That said, judging runs **Sept 1 – Oct 1** and a judge who can click through and poke at a working dashboard scores you better than one who can't. Set a billing alert, seed the database so it isn't an empty page, and check it weekly. Winners announced Oct 8.

**Video rules are strict.** ≤4 minutes (only the first 4 minutes are evaluated — anything after is wasted), English or English subtitles, public on YouTube or Vimeo, must show **unedited live execution** and proof of Google Cloud deployment. Unedited means you cannot cut around a failure — hence the three dry runs on Aug 29.

**Private repo is allowed**, but you must grant access to **testing@devpost.com** and **cloudhackathons@google.com**, and the README must contain detailed spin-up instructions.

**Multiple submissions are permitted** if each is "unique and substantially different." Tempting to also enter the Terraform agent — don't. At 40 hours solo, two half-finished projects beat neither. One project, one category.

**Eligibility:** Germany is fine. The excluded list is Italy, Quebec, Crimea, Cuba, Iran, Syria, North Korea, Sudan, Belarus, Russia.

**IP:** you keep ownership of everything. You grant Google a perpetual non-exclusive license to use it for evaluation and promotion.

---

## 9. Video script (4:00)

| Time | Beat |
|---|---|
| 0:00–0:25 | The problem, concretely. A 3am page for a bad config rollout. Then: *"Warden's agents have no production credentials. Their only write primitive is a pull request."* |
| 0:25–1:00 | Architecture diagram, 35 seconds, narrated. Signals → bus → fleet → policy proxy → estate. Name the control plane pieces. |
| 1:00–2:30 | **Live, unedited.** Inject the bad config. Watch triage fire, the diagnostician reason, the PR appear on GitHub with a real diff, the merge, the verifier close the incident. Cut to the Cloud Trace tree spanning all four agents. |
| 2:30–3:10 | The denial scene. Agent tries to delete the workload, proxy refuses, audit log shows the denial and the reason. Then hit the kill switch mid-incident and show the fleet drain. |
| 3:10–3:40 | Cloud console: Cloud Run services, Pub/Sub topic, Firestore collections. This is your deployment proof — don't skip it, it's a stated requirement. |
| 3:40–4:00 | Cost per incident (the Gemma routing decision), and what the fleet looks like at 200 services. |

---

## 10. Submission checklist

- [ ] Category selected: **Fortified Enterprise Fleet**
- [ ] Hosted URL, live and seeded
- [ ] Text description: features, technologies, data sources, learnings
- [ ] Repo with spin-up instructions in README (tested from a clean clone). If private: access granted to `testing@devpost.com` and `cloudhackathons@google.com`
- [ ] Architecture diagram
- [ ] Demo video ≤4 min, unedited execution, Google Cloud proof
- [ ] Pre-existing code disclosed (should be: none)
- [ ] Bonus: blog post
- [ ] Bonus: social post with `#AllThingsAgenticHackathon`
- [ ] Bonus: Gemma integration documented in the description
- [ ] Billing alert set so the URL survives to Oct 1

---

## Key links

Rules: https://allthingsagentichackathon.devpost.com/rules · Resources: https://allthingsagentichackathon.devpost.com/resources
ADK docs: https://google.github.io/adk-docs · ADK Python: https://github.com/google/adk-python
Agent Runtime: https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime
Memory Bank: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank
Deploy ADK to Cloud Run: https://google.github.io/adk-docs/deploy/cloud-run/
Credits form (closes Aug 28, 12:00 PT): https://forms.gle/5PtXmw1dSbDnpYke9
Discord: https://discord.gg/HP4BhW3hnp

**Remaining webinar:** Aug 27 — Agent Memory Architecture (session state, vector search, managed cloud memory). Directly relevant to your Memory Bank work that same day.
