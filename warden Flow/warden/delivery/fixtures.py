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


GOOD_PIPELINE = """\
name: deliver
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
jobs:
  build-test-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: docker build -t checkout-svc:${{ github.sha }} .
      - name: Test
        run: python -m pytest -q
      - name: Scan image (fail on HIGH/CRITICAL)
        uses: aquasecurity/trivy-action@0.24.0
        with:
          image-ref: checkout-svc:${{ github.sha }}
          severity: HIGH,CRITICAL
          exit-code: '1'
  push-deploy:
    needs: build-test-scan
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - name: Log in to registry
        run: echo "${{ secrets.REGISTRY_PASSWORD }}" | docker login "${{ secrets.REGISTRY }}" -u "${{ secrets.REGISTRY_USER }}" --password-stdin
      - name: Push
        run: docker push "${{ secrets.REGISTRY }}/checkout-svc:${{ github.sha }}"
      - name: Deploy
        run: kubectl set image deployment/checkout-svc checkout=${{ secrets.REGISTRY }}/checkout-svc:${{ github.sha }}
"""

DEPLOY_DEPLOYMENT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: checkout-svc
  namespace: demo
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate: { maxSurge: 1, maxUnavailable: 0 }
  selector:
    matchLabels: { app: checkout-svc }
  template:
    metadata:
      labels: { app: checkout-svc }
    spec:
      securityContext: { runAsNonRoot: true, runAsUser: 10001 }
      containers:
        - name: checkout
          image: registry.example.com/checkout-svc@sha256:PINNED_DIGEST
          ports: [{ containerPort: 8080 }]
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits:   { cpu: 500m, memory: 256Mi }
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: { drop: ["ALL"] }
          readinessProbe:
            httpGet: { path: /, port: 8080 }
            initialDelaySeconds: 3
          livenessProbe:
            httpGet: { path: /, port: 8080 }
            initialDelaySeconds: 10
"""

DEPLOY_SERVICE = """\
apiVersion: v1
kind: Service
metadata:
  name: checkout-svc
  namespace: demo
spec:
  selector: { app: checkout-svc }
  ports: [{ port: 80, targetPort: 8080 }]
"""

PIPELINE_SCRIPT = [
    {
        "json": {
            "content": GOOD_PIPELINE,
            "stages": ["build", "test", "scan", "push", "deploy"],
            "rationale": "Build/test/scan run on every push and PR; push and deploy are gated on the main branch. The image is scanned with Trivy and the job fails on HIGH/CRITICAL. Registry credentials come from secrets and are never echoed; the workflow token is read-only by default.",
        }
    },
]

DEPLOY_PLAN_SCRIPT = [
    {
        "json": {
            "manifests": {
                "k8s/deployment.yaml": DEPLOY_DEPLOYMENT,
                "k8s/service.yaml": DEPLOY_SERVICE,
            },
            "strategy": "RollingUpdate, maxSurge=1, maxUnavailable=0",
            "rollback": "kubectl rollout undo deployment/checkout-svc restores the previous ReplicaSet.",
            "rationale": "Three replicas with a surge-one rolling update keep the service available during deploys; requests/limits, probes, a non-root read-only securityContext and a digest-pinned image are all set.",
        }
    },
]

VERIFY_SCRIPT = [
    {
        "json": {
            "checks": [
                "Dockerfile: pinned base, multi-stage, non-root, no baked secret",
                "Pipeline: scan stage present, push gated on main, secrets referenced, least-privilege permissions",
                "Manifests: resource limits set, probes present, non-root securityContext, image pinned by digest",
            ],
            "passed": True,
            "issues": [],
        }
    },
]


def delivery_scripted_models() -> dict[str, ScriptedModel]:
    return {
        "assess": ScriptedModel(model="scripted/assess", script=ASSESS_SCRIPT),
        "containerize": ScriptedModel(model="scripted/containerize", script=CONTAINERIZE_SCRIPT),
        "pipeline": ScriptedModel(model="scripted/pipeline", script=PIPELINE_SCRIPT),
        "deploy_plan": ScriptedModel(model="scripted/deploy_plan", script=DEPLOY_PLAN_SCRIPT),
        "verify_artifacts": ScriptedModel(model="scripted/verify", script=VERIFY_SCRIPT),
    }
