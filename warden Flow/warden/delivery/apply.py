"""The Apply step — build, push to a registry, and deploy.

This is DELIBERATELY not an LLM node. Everything before it is model-generated and
reviewed by a human; Apply only *executes* the approved artifacts with real
credentials. An LLM improvising `docker push` and `kubectl apply` commands is
exactly what you do not want touching production.

It runs only after a human has approved, and only when `execute=True` and the
credentials are present. Otherwise it prints the exact plan — the commands it
would run — and changes nothing.

Access (set in .env or the environment):

    # Azure Container Registry
    ACR_REGISTRY=myregistry.azurecr.io
    ACR_USERNAME=<sp-app-id or 'token'>
    ACR_PASSWORD=<sp-password or an ACR token>

    # Deploy target — one of:
    DEPLOY_KIND=aks            # uses kubectl + your current kubeconfig/KUBECONFIG
    #   or
    DEPLOY_KIND=containerapp   # uses the az CLI
    CONTAINERAPP_NAME=checkout-svc
    AZURE_RESOURCE_GROUP=my-rg

The registry password never lands on disk and is redacted in the printed plan;
it only appears in the argv of the one `docker login` subprocess.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Step:
    label: str
    cmd: list[str]
    secret_positions: tuple[int, ...] = ()  # argv indices to redact when printing
    cwd: str | None = None

    def printable(self) -> str:
        parts = list(self.cmd)
        for i in self.secret_positions:
            if 0 <= i < len(parts):
                parts[i] = "***"
        return " ".join(parts)


def build_plan(*, source_dir: str, app: str, tag: str, manifests_dir: str) -> list[Step]:
    """The command sequence to build → push → deploy. Pure; runs nothing."""
    registry = os.environ.get("ACR_REGISTRY", "<ACR_REGISTRY>")
    image = f"{registry}/{app}:{tag}"
    user = os.environ.get("ACR_USERNAME", "<ACR_USERNAME>")
    pw = os.environ.get("ACR_PASSWORD", "<ACR_PASSWORD>")
    deploy_kind = os.environ.get("DEPLOY_KIND", "aks")

    steps = [
        Step("build image", ["docker", "build", "-t", image, source_dir]),
        Step("log in to registry",
             ["docker", "login", registry, "-u", user, "-p", pw],
             secret_positions=(6,)),
        Step("push image", ["docker", "push", image]),
    ]

    if deploy_kind == "containerapp":
        app_name = os.environ.get("CONTAINERAPP_NAME", app)
        rg = os.environ.get("AZURE_RESOURCE_GROUP", "<AZURE_RESOURCE_GROUP>")
        steps.append(Step(
            "deploy (Azure Container Apps)",
            ["az", "containerapp", "update", "-n", app_name, "-g", rg, "--image", image],
        ))
    else:  # aks / kubectl
        steps.append(Step("apply manifests", ["kubectl", "apply", "-f", manifests_dir]))
        steps.append(Step(
            "roll the image", ["kubectl", "set", "image", f"deployment/{app}", f"{app}={image}"]
        ))
    return steps


def _creds_present() -> bool:
    return bool(os.environ.get("ACR_REGISTRY") and os.environ.get("ACR_PASSWORD"))


def write_artifacts(
    source_dir: str, dockerfile: str, pipeline: str, manifests: dict[str, str]
) -> list[str]:
    """Write the approved DevOps files into the repo — this is what the agent
    hands the developer. Returns the paths written (repo-relative)."""
    src = Path(source_dir)
    written = []

    (src / "Dockerfile").write_text(dockerfile)
    written.append("Dockerfile")

    if pipeline:
        wf = src / ".github" / "workflows" / "deliver.yml"
        wf.parent.mkdir(parents=True, exist_ok=True)
        wf.write_text(pipeline)
        written.append(".github/workflows/deliver.yml")

    for path, yaml in manifests.items():
        (src / path).parent.mkdir(parents=True, exist_ok=True)
        (src / path).write_text(yaml)
        written.append(path)

    return written


def run_apply(*, source_dir: str, app: str, tag: str, execute: bool) -> dict:
    """Print the build → push → deploy plan, or run it when execute and creds are set."""
    mdir = str(Path(source_dir) / "k8s")
    plan = build_plan(source_dir=source_dir, app=app, tag=tag, manifests_dir=mdir)

    if not execute:
        return {"executed": False, "reason": "plan only — pass --apply and set ACR creds to run",
                "plan": [s.printable() for s in plan]}
    if not _creds_present():
        return {"executed": False, "reason": "missing ACR_REGISTRY / ACR_PASSWORD in env",
                "plan": [s.printable() for s in plan]}

    results = []
    for step in plan:
        proc = subprocess.run(step.cmd, capture_output=True, text=True, cwd=step.cwd, timeout=600)
        results.append({"step": step.label, "cmd": step.printable(),
                        "ok": proc.returncode == 0,
                        "output": (proc.stdout + proc.stderr).strip()[-400:]})
        if proc.returncode != 0:
            break
    return {"executed": True, "results": results, "ok": all(r["ok"] for r in results)}
