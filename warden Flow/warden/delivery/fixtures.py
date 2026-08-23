"""Scripted stand-ins for the DELIVER nodes, so the workflow runs offline and
free (ADR-006, same rationale as the incident fixtures).

Each node's script emits its final structured answer directly — no tool calls —
so an offline run needs no repo access and no credentials. `--live` swaps these
for real models and the nodes read the repo for real.
"""

from __future__ import annotations

from warden.agents.fixtures import ScriptedModel

# A correct, production-shaped Dockerfile for the stdlib checkout-svc. This is
# what the Containerize node's constraints (pinned, multi-stage, non-root)
# produce — and what --live should reproduce.
GOOD_DOCKERFILE = """\
# syntax=docker/dockerfile:1
FROM python:3.12.6-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12.6-slim
RUN useradd --system --uid 10001 appuser
WORKDIR /app
COPY --from=build /install /usr/local
COPY main.py ./
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/').status==200 else 1)"
ENTRYPOINT ["python", "-u", "main.py"]
"""

ASSESS_SCRIPT = [
    {
        "json": {
            "language": "python",
            "framework": "none",
            "entrypoint": "python main.py",
            "ports": [8080],
            "build_system": "none (Python standard library)",
            "dependencies": [],
            "notes": "Plain stdlib http.server service; validates PAYMENT_ENDPOINT on startup, serves :8080. Entrypoint is main.py at the repo root.",
        }
    },
]

CONTAINERIZE_SCRIPT = [
    {
        "json": {
            "content": GOOD_DOCKERFILE,
            "base_image": "python:3.12.6-slim",
            "multistage": True,
            "runs_as_nonroot": True,
            "rationale": "Multi-stage keeps build tooling out of the runtime image; the base is pinned to a patch version; the final stage drops to a dedicated non-root uid and copies only the app and its installed deps.",
            "security_notes": [
                "pinned base image (python:3.12.6-slim, not :latest)",
                "multi-stage build — no compilers in the runtime image",
                "runs as non-root user appuser (uid 10001)",
                "no secrets copied into any layer",
                "explicit non-privileged EXPOSE 8080 + HEALTHCHECK",
            ],
        }
    },
]


def delivery_scripted_models() -> dict[str, ScriptedModel]:
    return {
        "assess": ScriptedModel(model="scripted/assess", script=ASSESS_SCRIPT),
        "containerize": ScriptedModel(model="scripted/containerize", script=CONTAINERIZE_SCRIPT),
    }
