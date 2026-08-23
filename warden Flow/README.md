# Warden Flow

**Warden Flow is an AI DevOps automation layer that turns an application repository into production-ready delivery artifacts—so developers can stay focused on building the product.**

Give it a local repository or GitHub URL. Warden Flow inspects the application, creates the container, CI/CD workflow, and deployment configuration it needs, validates the result, and returns the work for review. It can open a pull request or, after explicit approval, execute the build → push → deploy plan.

```text
your application code
        ↓
assess → containerize → CI/CD → deployment plan → validate → human review → deploy
```

The workflow also includes an incident-response path for diagnosing a running workload and proposing a small GitOps fix. Both paths use the same guardrails, audit trail, and human approval boundary.

## What developers get

For a supported service, Warden Flow produces:

- A production-minded `Dockerfile` with a pinned base image, multi-stage build, non-root runtime, and no baked-in secrets.
- A GitHub Actions workflow covering build, test, vulnerability scan, image push, and deployment.
- Kubernetes deployment manifests with resource limits, probes, a non-root security context, immutable image references, and a rollback plan.
- Deployment-aware CI instructions for Azure Container Apps, AKS, or Azure App Service.
- A validation report describing what passed and what needs attention.

It reads your application to understand its language, dependencies, entrypoint, and ports. It does not rewrite your product code or silently apply infrastructure changes.

## Quick start

From the `warden Flow` directory:

```bash
./setup.sh --deliver
```

This runs the delivery workflow against the bundled sample using scripted models. It is deterministic, free, and requires no cloud account or API key.

To run it against your own local service after setup:

```bash
.venv/bin/python -m warden.deliver --target /path/to/your-service
```

Or point it at a GitHub repository:

```bash
.venv/bin/python -m warden.deliver --target https://github.com/your-org/your-service
```

The default mode only generates and reports artifacts. Choose the handoff that fits your team:

```bash
# Write generated files into a local target repository
.venv/bin/python -m warden.deliver --target /path/to/your-service --write

# Open a reviewable PR on a GitHub target (requires GITHUB_TOKEN)
.venv/bin/python -m warden.deliver --target https://github.com/your-org/your-service --pr

# Write, then execute the build → push → deploy plan (requires registry/deployment credentials)
.venv/bin/python -m warden.deliver --target /path/to/your-service --apply
```

`--apply` is intentional and explicit: generation and validation never deploy by themselves.

## How the automation works

Each stage has one job and passes typed output to the next stage rather than asking one model to make every infrastructure decision at once.

| Stage | Responsibility | Output |
| --- | --- | --- |
| Assess | Inspect the codebase, dependencies, entrypoint, and ports | `RepoProfile` |
| Containerize | Create a secure, production-ready Dockerfile | `Dockerfile` |
| Pipeline | Create build, test, scan, push, and deploy automation | `Pipeline` |
| Deploy plan | Create manifests, rollout strategy, and rollback guidance | `DeployPlan` |
| Validate | Check the generated artifacts before review | `VerifyReport` |

The pipeline stage adapts its deployment instructions to `DEPLOY_TARGET`:

- `containerapp` (default) for Azure Container Apps
- `aks` for Azure Kubernetes Service
- `appservice` for Azure App Service containers

Set it in `.env` before a live run, for example `DEPLOY_TARGET=aks`.

## Safety and ownership

Warden Flow automates DevOps work without taking ownership away from the engineering team.

- Application developers own application code and review the generated operational artifacts.
- Generated artifacts are validated before they are handed off.
- A PR is the normal collaboration boundary for remote repositories.
- Deployments require the explicit `--apply` action and valid deployment credentials.
- The workflow is audited, policy-governed, and budget-limited.
- Secrets are referenced through CI/CD secrets and environment configuration, not written into generated artifacts.

The incident workflow follows the same principle: it can investigate, prepare a small GitOps patch, and propose it for review, but it does not receive unrestricted production write access.

## Running with live models

Offline commands use scripted models. For live generation, copy `.env.example` to `.env` and configure a model provider.

Gemini is supported directly. Azure OpenAI, OpenAI, and Anthropic are supported through LiteLLM. For example, to use an Azure OpenAI deployment:

```bash
# .env
DELIVER_MODEL=azure/<your-deployment-name>
AZURE_API_KEY=...
AZURE_API_BASE=https://<resource>.openai.azure.com/
AZURE_API_VERSION=2024-12-01-preview
```

Then run:

```bash
make deliver-live
```

## Common commands

| Command | Purpose |
| --- | --- |
| `./setup.sh --deliver` | Run the offline delivery workflow |
| `make deliver-live` | Run delivery with a live model |
| `make bench-deliver` | Compare staged delivery against a single prompt, offline |
| `make bench-deliver-live` | Run that comparison with a live model |
| `make demo` | Run the offline incident-response workflow |
| `make test` | Run the test suite |
| `make probe` | Print the policy matrix |
| `make dashboard` | Run the workflow dashboard locally |

## Repository layout

```text
warden/delivery/       delivery orchestration, source handling, PR publishing, apply plan
manifests/delivery/    versioned manifests for the delivery stages
warden/agents/         incident-response workflow and delivery prompts
warden/control_plane/  policy, budgets, manifests, and audit store
warden/tools/          controlled repository, source, and infrastructure tool surface
docs/reverie/          workflow details and benchmark material
```

## Why staged automation

`warden bench-deliver` evaluates the staged workflow against a single broad prompt on the same service. It scores observable Dockerfile safeguards—such as a pinned base, multi-stage build, non-root runtime, health check, and absence of baked secrets—rather than relying on a qualitative claim.

That separation is the core design choice: developers supply the application expertise; Warden Flow handles the repeatable delivery engineering around it, with reviewable output and clear operational boundaries.
