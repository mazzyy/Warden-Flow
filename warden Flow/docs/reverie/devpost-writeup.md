# Warden Flow — Devpost writeup

**Track:** ML Prompt Engineering

---

## Inspiration

I've written more or less the same Dockerfile about forty times. Different company, different language, same five decisions: pin the base, don't run as root, multi-stage it, don't bake the token in, wire up a health check. Then the same CI pipeline. Then the same manifests with the same resource limits I copy from the last project.

It's the tax you pay between "the code works" and "the code is running." Alone, you pay it at midnight and cut corners you don't tell anyone about. On a team, one person quietly becomes the DevOps bottleneck and their calendar fills with other people's deploys. At a company, you hire someone whose entire job is this, and they spend most of it on work they've done before.

The obvious move is to hand it to an LLM. We tried that first, and it's worse than it looks. Ask a model to "write me a Dockerfile" and you get something confident that builds fine and runs as root from `python:latest` with an API token sitting in an `ENV` layer. It doesn't fail loudly. It fails in a way you find out about later.

So the question we actually wanted to answer was: if a single prompt isn't safe enough to ship, what *is*? Our bet was that the answer is structure, not a longer prompt.

## What it does

Warden Flow is an AI DevOps engineer with two workflows that share one governance core.

**DELIVER** takes a repository — a GitHub URL or a local path — and produces the operational scaffolding it's missing. Five nodes run in sequence: `assess` reads the code and reports what the service actually is, `containerize` writes a production Dockerfile from that profile, `pipeline` writes the CI/CD workflow, `deploy_plan` writes the manifests and rollback, and `verify_artifacts` checks all three before a human sees them. The result arrives as a pull request.

**OPERATE** is the original Warden, pointed the other way. A production alert comes in and `triage` decides whether it's real or noise, `diagnostician` reads logs and metrics read-only and names one root cause with a cited evidence chain, `remediator` turns that into the smallest possible patch, and after a human merges, `verifier` independently checks whether the service actually recovered. If it didn't, it opens a revert PR and the loop runs again.

Both workflows have exactly one write primitive: opening a pull request. No node holds a cluster credential, a registry credential, or the ability to merge its own work. The thing that changes production is a person clicking merge.

## How we built it

Every node is a separate LLM call with one job, a Pydantic schema the runtime enforces on its output, a list of tools it's allowed to call, and a token and tool-call budget. The typed output isn't decoration — it's the handoff. `assess` returns a `RepoProfile`, and `containerize` reasons over that structure rather than re-reading the repo from scratch. If a node returns something that doesn't parse, that's a failed node and the workflow stops rather than passing nothing downstream.

The runtime is Google's Agent Development Kit. Non-Gemini models route through LiteLLM, so the same workflow runs on Gemini, Azure OpenAI, OpenAI or Anthropic without touching orchestration code. The live DELIVER demo runs on Azure GPT-5.6; OPERATE runs on `gemini-3.5-flash`.

What an agent is *allowed* to do lives in a YAML manifest, not in Python. Tools, model, token ceiling, and blast radius are all declared there, which means changing an agent's authority is a reviewable diff. The remediator is capped at twelve changed lines. It's not a suggestion in a prompt — the write path refuses a larger patch.

The prompts themselves are the part we spent the most time on, and they're versioned in the repo alongside the code, because a prompt that decides whether your deploy gate is correct is code.

## Challenges we ran into

This is the honest part, and it's most of what we actually learned.

Our first real live run looked like a complete success. The agent read `github.com/mazzyy/testing-python`, correctly identified it as a Vite frontend despite the repo name, generated a clean multi-stage Dockerfile, a full pipeline, and manifests. The Verify node passed it. We opened PR #3, reviewed it, merged it.

Nothing deployed.

The generated pipeline gated its push and deploy jobs on `if: github.ref == 'refs/heads/main'`. That repository's default branch is `master`. So after the merge the deploy job skipped — silently, forever, with a green checkmark, because a skipped job and a successful job look identical at a glance. The agent had correctly detected `master` when it opened the PR *against* it, and then written `main` into the pipeline anyway.

Two more surfaced right behind it. The pipeline referenced `aquasecurity/trivy-action@0.33.1`; the real tag is `v0.33.1`, so GitHub couldn't resolve it and the scan job died in about two seconds. And once we fixed the tag, the installer action turned out to fetch Trivy's binary from the GitHub API, which rate-limits on shared runners and fails for reasons that have nothing to do with your code.

A human — sitting there reading Actions logs — had to fix all three by hand. Which fairly comprehensively undermines the phrase "AI DevOps engineer."

The uncomfortable realization was that our Verify node could never have caught any of them. It reads the generated YAML and checks it statically. It cannot know whether an action tag exists on GitHub, or whether a branch gate matches the repo's actual default. Static validation has a hard ceiling, and everything past that ceiling only shows up when the pipeline actually runs.

Then we found the pattern underneath all of it, which is the thing we'd fix first if we started over. **We kept asking the model for facts the system already had.** We clone the repository, so the default branch is sitting on disk — and we asked an LLM to guess it. The GitHub API returns the pull request URL the instant `propose_patch` succeeds — and we asked the remediator to copy that URL into its structured output, which it sometimes forgot to do, leaving incidents with no link to their own pull request and an empty button on the dashboard. Neither of those is a prompting problem. We'd handed the model a job that belonged to the code.

And one more, after we thought we were done. We tightened the containerize prompt, re-ran it, got a fresh PR with a correct default-branch gate and a containerized scanner and no hand edits at all — and the scan stage failed with 21 HIGH and CRITICAL vulnerabilities. The base image was pinned exactly as instructed. Pinned to `alpine:3.20.3`, which reached end of life in April 2026 and hasn't received a security update since. The prompt said pin, so it pinned, into a dead release.

## Accomplishments that we're proud of

The fix for the branch gate worked, and we can point at the diff. After we moved the rule into one place and stopped hardcoding a branch name, a completely fresh live run generated a pipeline gated on `github.event.repository.default_branch`, running Trivy from its official container image instead of a flaky installer. No human touched that file. That's the run we wanted the first time.

The scan gate catching our own end-of-life base image is, weirdly, the thing we're happiest about. The system caught a real production defect that its own author had shipped and that its own validation node structurally could not see. That's a governance story you can't fake in a demo.

And triage refusing to escalate. Point it at a healthy service and it returns `severity: noise, escalate: false` and closes the incident for about two cents, without waking anything. An agent fleet that declines to act is harder to build than one that always finds something to fix.

The governance spine turning out to be workflow-agnostic was the nicest surprise. The same policy, budget, audit and human-approval code runs a proactive delivery workflow and a reactive incident workflow with no changes. That wasn't luck, but it also wasn't guaranteed.

## What we learned

The most useful rule we found is a split: **facts the system already holds get injected as data or enforced after generation; only judgment goes to the model.** Default branch, registry name, port numbers, the PR URL — all facts. "Is a read-only root filesystem safe for this service" — judgment. Every bug in the challenges section above is a violation of that one line.

Structure beats sentence-level prompting. We didn't make our nodes reliable by telling them to be more careful. We made them reliable by removing the room to be careless — one job per node, an enforced schema on the way out, a tool list they can't exceed, and a blast radius that refuses an over-eager patch at the write path rather than asking the model not to write one.

Duplicated prompts drift. We had the same pipeline instruction in three places, and patching one of them left the other two generating the old bug. Now there's one definition.

And a gate that can pass on something missing is worse than no gate. Two of our nodes didn't check whether the previous node's output parsed, which meant Verify could be handed the literal string `(none)` for the pipeline and still report green. We'd have believed it.

## What's next for Warden Flow

The clear next step is closing the loop. Right now Verify reads text; the version we want reads the GitHub Actions result for the pull request it just opened, and repairs the artifacts until the pipeline is actually green. That turns "plausible YAML" into "proven-green YAML" and it's the real answer to everything in the challenges section.

After that: prompt versioning in the audit trail. Every run already records the model, token count and every tool call, but not which revision of the prompt produced the output. Hashing the instruction text and storing it on the run record is about thirty lines, and it would let us answer "did quality change when I edited the containerize prompt" with data instead of a feeling.

Then collapsing the two orchestrators into one, so the CLI and the dashboard can't diverge. And routing the cheap nodes to cheaper models — triage burns 3,000 tokens to decide whether to escalate, which doesn't need the same model as writing a Dockerfile.

---

### Tagline
An AI DevOps engineer built as a multi-node LLM workflow — structure, not a bigger prompt, is what makes its output safe enough to ship.

### Built with
Python · Google Agent Development Kit (ADK) · Pydantic structured outputs · Azure OpenAI GPT-5.6 · Google Gemini 3.5 Flash · LiteLLM · FastAPI · React · GitHub Apps · Azure Container Registry · Azure Container Apps · Terraform · Trivy

### Submission artifacts
- `warden-flow-ml-workflow.png` — the full ML workflow flowchart: both workflows, every prompt, model per node, human input points, and the revert loop
- `warden-flow-deliver.png` / `warden-operate.png` — one-screen versions of each workflow
- `node-documentation.md` — the reasoning behind each node
- `workflow-vs-single-prompt.md` — the same task, structured workflow vs a single prompt
- Repo: https://github.com/mazzyy/Warden-Flow
