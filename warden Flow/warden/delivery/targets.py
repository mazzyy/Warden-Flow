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
