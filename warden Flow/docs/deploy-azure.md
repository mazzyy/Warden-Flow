# Azure Deployment Runbook — Warden Flow

_Everything the DELIVER pipeline needs on the Azure + GitHub side, so this does not have to be rebuilt. Last updated 2026-08-24._

**Target repo being deployed:** https://github.com/mazzyy/testing-python
(default branch **`master`**; it's a Node/Vite frontend — `node:20` build, `nginx-unprivileged` runtime.)

**Where it deploys:** Azure **Container Apps** app `testing-python` in resource group `warden-rg`, image pulled from ACR `mazzyacr2026`. The CI pushes `mazzyacr2026.azurecr.io/testing-python:<git-sha>` and runs `az containerapp update --image …:<sha>`.

> Secrets note: the only true secret below is the service-principal **clientSecret** (inside `AZURE_CREDENTIALS`). It is **not** stored in this file or the repo — only in GitHub Actions Secrets. To (re)generate it, run the `az ad sp credential reset` command in §5. Rotate all creds after the hackathon.

---

## 1. Resources already provisioned

| Thing | Value |
| --- | --- |
| Subscription ID | `77f69e31-9603-4766-8e47-93a380c2cfd1` |
| Region | `germanywestcentral` (confirm: `az group show -n warden-rg --query location -o tsv`) |
| Resource group | `warden-rg` |
| Container Registry (ACR) | `mazzyacr2026` — login server `mazzyacr2026.azurecr.io` |
| Container App | `testing-python` |
| Service principal | `warden-ci` — clientId `5943100b-8226-4776-98d6-d7517cef21aa` |
| SP role (current) | **AcrPush** on the ACR |
| SP role (needed for deploy) | **Contributor** on `warden-rg` — ✅ granted 2026-08-24 (assignment `c8d6bc4c-…`) |

---

## 2. GitHub Actions configuration on `mazzyy/testing-python`

Settings → Secrets and variables → Actions.

**Secret (Secrets tab):**

| Name | Value |
| --- | --- |
| `AZURE_CREDENTIALS` | the full `--sdk-auth` JSON from `az ad sp create-for-rbac` (contains clientId/clientSecret/subscriptionId/tenantId). Paste the entire JSON block. |

**Variables (Variables tab):**

| Name | Value |
| --- | --- |
| `ACR_NAME` | `mazzyacr2026` |
| `ACR_LOGIN_SERVER` | `mazzyacr2026.azurecr.io` |
| `IMAGE_NAME` | `testing-python` |
| `CONTAINERAPP_NAME` | `testing-python` |
| `AZURE_RESOURCE_GROUP` | `warden-rg` |

The pipeline references these as `${{ secrets.AZURE_CREDENTIALS }}` and `${{ vars.* }}`. If a re-generated pipeline names a variable differently, either rename the GitHub variable to match or fix the pipeline — the names must be identical.

---

## 3. `.env` (on the Mac) — deploy-relevant keys

```
DEPLOY_TARGET=containerapp
AZURE_SUBSCRIPTION_ID=77f69e31-9603-4766-8e47-93a380c2cfd1
AZURE_REGION=germanywestcentral
# model creds (Azure GPT-5.6) also live here — see README "Live models"
```

---

## 4. Rebuild from scratch (if the resources are ever gone)

Run once, logged in with `az login`. Names must stay in sync with §2.

```bash
# 0. variables
RG=warden-rg
LOC=germanywestcentral
ACR=mazzyacr2026
APP=testing-python
ENVI=warden-env          # Container Apps environment

# 1. resource group
az group create -n "$RG" -l "$LOC"

# 2. container registry
az acr create -g "$RG" -n "$ACR" --sku Basic

# 3. container apps environment + app (placeholder image to start)
az extension add --name containerapp --upgrade
az containerapp env create -g "$RG" -n "$ENVI" -l "$LOC"
az containerapp create -g "$RG" -n "$APP" \
  --environment "$ENVI" \
  --image mcr.microsoft.com/k8se/quickstart:latest \
  --target-port 8080 --ingress external
```

The CI pipeline replaces that placeholder image on the first deploy.

---

## 5. Service principal for CI (`AZURE_CREDENTIALS`)

The SP was created with AcrPush so CI can push images:

```bash
ACR_ID=$(az acr show -n mazzyacr2026 --query id -o tsv)
az ad sp create-for-rbac \
  --name warden-ci \
  --role AcrPush \
  --scopes "$ACR_ID" \
  --sdk-auth
# → copy the ENTIRE JSON output into the AZURE_CREDENTIALS GitHub secret
```

**Deploy also needs the SP to update the Container App.** AcrPush alone does not authorize `az containerapp update`. ✅ **Already granted** (Contributor on `warden-rg`, 2026-08-24). The command used, for reference / rebuild:

```bash
SP_ID=5943100b-8226-4776-98d6-d7517cef21aa
SUB=77f69e31-9603-4766-8e47-93a380c2cfd1
# broad (simplest):
az role assignment create --assignee "$SP_ID" \
  --role Contributor \
  --scope "/subscriptions/$SUB/resourceGroups/warden-rg"
# tighter alternative: scope to the container app resource id instead of the whole RG
```

To rotate the secret (do this after the hackathon):

```bash
az ad sp credential reset --id 5943100b-8226-4776-98d6-d7517cef21aa
# then update the AZURE_CREDENTIALS GitHub secret with the new JSON
```

---

## 6. How the pipeline deploys (what the deploy job runs)

On push to `master`, after build → test → scan → push:

```bash
az acr login --name "$ACR_NAME"
docker push "$ACR_LOGIN_SERVER/$IMAGE_NAME:<git-sha>"
az containerapp update \
  --name "$CONTAINERAPP_NAME" \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --image "$ACR_LOGIN_SERVER/$IMAGE_NAME:<git-sha>"
```

`DEPLOY_TARGET=containerapp` makes the DELIVER Pipeline node generate exactly this. Switching to AKS or App Service is a one-line `.env` change (`DEPLOY_TARGET=aks|appservice`) plus the matching per-target variables (`AKS_CLUSTER`, or `WEBAPP_NAME`).

---

## 7. Verify a deploy landed

```bash
az containerapp show -g warden-rg -n testing-python \
  --query "properties.template.containers[0].image" -o tsv
# should print mazzyacr2026.azurecr.io/testing-python:<the merged commit sha>

az containerapp show -g warden-rg -n testing-python \
  --query "properties.configuration.ingress.fqdn" -o tsv
# the public URL to open
```
