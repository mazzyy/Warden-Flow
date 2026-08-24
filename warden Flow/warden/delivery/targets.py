"""Deploy-target recipes injected into the Pipeline node's prompt, so the CI
deploy job it generates matches where you actually deploy.

Set DEPLOY_TARGET in .env: containerapp (default) | aks | appservice.
"""

from __future__ import annotations

import os

_TARGETS = {
    "containerapp": (
        "DEPLOY TARGET — Azure Container Apps. The deploy job must:\n"
        "  - authenticate with azure/login@v2 using ${{ secrets.AZURE_CREDENTIALS }} "
        "(a service-principal JSON produced by `az ad sp create-for-rbac --sdk-auth`);\n"
        "  - log in to and push the image to Azure Container Registry: "
        "`az acr login --name ${{ vars.ACR_NAME }}`, then tag and docker push to "
        "${{ vars.ACR_LOGIN_SERVER }}/${{ vars.IMAGE_NAME }}:${{ github.sha }};\n"
        "  - update the app to that EXACT image: "
        "`az containerapp update --name ${{ vars.CONTAINERAPP_NAME }} "
        "--resource-group ${{ vars.AZURE_RESOURCE_GROUP }} "
        "--image ${{ vars.ACR_LOGIN_SERVER }}/${{ vars.IMAGE_NAME }}:${{ github.sha }}`.\n"
        "Never deploy ':latest' or a placeholder. Container Apps runs the container "
        "directly, so the k8s manifests are reference only for this target."
    ),
    "aks": (
        "DEPLOY TARGET — Azure Kubernetes Service (AKS). The deploy job must "
        "authenticate with azure/login@v2 (${{ secrets.AZURE_CREDENTIALS }}), fetch "
        "kubeconfig with `az aks get-credentials --name ${{ vars.AKS_CLUSTER }} "
        "--resource-group ${{ vars.AZURE_RESOURCE_GROUP }}`, `kubectl apply -f k8s/`, "
        "then `kubectl set image deployment/<name> <container>=<ACR image>:${{ github.sha }}` "
        "to roll the exact image just pushed. Never ':latest' or a placeholder."
    ),
    "appservice": (
        "DEPLOY TARGET — Azure App Service (Web App for Containers). The deploy job "
        "must authenticate with azure/login@v2 (${{ secrets.AZURE_CREDENTIALS }}) and "
        "run `az webapp config container set --name ${{ vars.WEBAPP_NAME }} "
        "--resource-group ${{ vars.AZURE_RESOURCE_GROUP }} --docker-custom-image-name "
        "<ACR image>:${{ github.sha }}`. Never ':latest' or a placeholder."
    ),
}


def deploy_hint() -> str:
    target = os.environ.get("DEPLOY_TARGET", "containerapp").strip().lower()
    return _TARGETS.get(target, _TARGETS["containerapp"])


# --------------------------------------------------------------------------
# Pipeline rules — ONE definition, injected into every path that asks a model
# for a workflow. This used to be an inline "push (main only)" string repeated
# in `deliver()`, in `deliver_events()` and in the node instruction, which is
# exactly how the three drifted apart and how a generated pipeline shipped a
# `main` gate to a repo whose default branch is `master`.
#
# The rules below encode the two failure modes observed on a real run:
#   1. a hardcoded branch name that does not match the repository, so the
#      deploy job silently never fires after merge;
#   2. a third-party action pinned to a tag that does not exist, or a scanner
#      installer that rate-limits on shared runners.
# Neither is catchable by static validation, so they are prevented at
# generation time instead.
# --------------------------------------------------------------------------

_DEFAULT_BRANCH_GATE = (
    "github.event_name == 'push' && "
    "github.ref_name == github.event.repository.default_branch"
)

PIPELINE_RULES = f"""\
Stages, in order: build, test, scan, push, deploy.

BRANCH GATING — never hardcode a branch name. This repository's default branch
is NOT necessarily 'main'. Gate the push and deploy jobs on the repository's own
default branch, exactly:

    if: {_DEFAULT_BRANCH_GATE}

A gate that names a branch literally ('refs/heads/main') is wrong even when it
happens to match: it breaks silently on any repo that uses a different default,
and a deploy job that never fires looks identical to one that succeeded.

THIRD-PARTY ACTIONS — pin every action to a tag that actually resolves. If you
are not certain a tag exists, do not invent one: run the tool from its official
container image instead. For vulnerability scanning, prefer

    docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \\
      aquasec/trivy:<pinned> image --exit-code 1 --severity HIGH,CRITICAL <image>

over an installer action — installers that fetch release binaries from the
GitHub API rate-limit on shared runners and fail the job for no real reason.

SECRETS — reference them as ${{{{ secrets.NAME }}}} and never echo one. Grant an
explicit minimal `permissions:` block, not the default write-all token."""


def pipeline_rules() -> str:
    """Branch-gating, action-pinning and secret rules for the Pipeline node."""
    return PIPELINE_RULES


def default_branch_gate() -> str:
    """The `if:` expression a correct push/deploy job must use."""
    return _DEFAULT_BRANCH_GATE


# Whether the Kubernetes manifests the deploy-plan node writes are the ACTIVE
# deploy artifact (a k8s target substitutes the image into them and applies them)
# or REFERENCE-ONLY (Container Apps / App Service run the container directly, so
# the manifests are portability documentation the pipeline never applies).
_MANIFEST_ROLE = {"aks": "active", "containerapp": "reference", "appservice": "reference"}


def manifest_role() -> str:
    target = os.environ.get("DEPLOY_TARGET", "containerapp").strip().lower()
    return _MANIFEST_ROLE.get(target, "reference")


def deploy_summary() -> str:
    """One paragraph stating the deploy target and, crucially, whether the k8s
    manifests are active or reference-only — injected into the deploy-plan and
    verify prompts so both judge the image placeholder against how this target
    actually ships."""
    target = os.environ.get("DEPLOY_TARGET", "containerapp").strip().lower()
    if target == "aks":
        return (
            "DEPLOY TARGET: Azure Kubernetes Service. The Kubernetes manifests are the "
            "ACTIVE deploy artifact — the pipeline substitutes the exact pushed image into "
            "them (kubectl set image / kustomize) and applies them."
        )
    if target == "appservice":
        return (
            "DEPLOY TARGET: Azure App Service (Web App for Containers). The pipeline sets the "
            "container image directly with `az webapp config container set "
            "--docker-custom-image-name <image>:<sha>`. Any Kubernetes manifests are "
            "REFERENCE-ONLY for portability and are NOT applied by this pipeline."
        )
    return (
        "DEPLOY TARGET: Azure Container Apps. The pipeline sets the container image directly "
        "with `az containerapp update --image <image>:<sha>` (commit-pinned). Any Kubernetes "
        "manifests are REFERENCE-ONLY for portability and are NOT applied by this pipeline."
    )
