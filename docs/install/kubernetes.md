---
title: Install with Kubernetes
description: Deploy GlycemicGPT to a Kubernetes cluster using the bundled Kustomize manifests.
---

> **Kubernetes is for users who already run a cluster.** If you're not sure whether that's you, [install with Docker](./docker.md) instead. Docker is simpler, faster to set up, and what most users run.

## When Kubernetes makes sense

You probably want this guide if:

- You already run a homelab with k3s, k0s, microk8s, RKE2, or a self-managed cluster
- You run a production cluster (EKS, GKE, AKS, etc.) and want to deploy GlycemicGPT alongside your other workloads
- You want HA, automatic failover, or multi-node ingress
- You're already using GitOps tooling (Flux, ArgoCD) and want GlycemicGPT to be part of it

If those don't describe you, Docker is the right choice.

> **Before you start, you need:**
>
> - A working Kubernetes cluster (any flavor, v1.25+)
> - An ingress controller installed (nginx-ingress, Traefik, or similar)
> - `kubectl` configured to talk to your cluster
> - A domain name pointing at your cluster's external IP (for TLS)
> - Familiarity with editing Kubernetes manifests

## Architecture

GlycemicGPT in Kubernetes runs as five Deployments plus PostgreSQL and Redis. The repository ships Kustomize manifests in the `k8s/` directory:

| Component | Purpose | Manifest |
|---|---|---|
| `web` | Next.js dashboard, port 3000 | `k8s/base/web.yaml` |
| `api` | FastAPI backend, port 8000 | `k8s/base/api.yaml` |
| `sidecar` | AI relay (LLM proxy), port 3456 | `k8s/base/sidecar.yaml` |
| `db` | PostgreSQL with PVC | `k8s/base/postgres.yaml` |
| `redis` | Redis cache | `k8s/base/redis.yaml` |
| Ingress | External access + TLS | `k8s/base/ingress.yaml` |
| cert-manager | Automatic TLS | `k8s/base/cert-manager-issuer.yaml` |
| Backup CronJob | Nightly database backups | `k8s/base/backup-cronjob.yaml` |

The base manifests are wired together by `k8s/base/kustomization.yaml`. Two overlays adjust them for different environments:

- `k8s/overlays/dev/` -- lower replica counts, locally-built images
- `k8s/overlays/prod/` -- production replicas, prebuilt images from `ghcr.io/glycemicgpt`, TLS-enabled ingress

## Quick deploy with prebuilt images

This path uses the prebuilt images published from the GlycemicGPT CI pipeline -- no need to build and push anything yourself. About 30-60 minutes end-to-end.

### 1. Clone the repository

```bash
git clone https://github.com/GlycemicGPT/GlycemicGPT.git
cd GlycemicGPT
```

### 2. Generate secrets

You need three random secrets:

```bash
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)"
echo "SECRET_KEY=$(openssl rand -hex 32)"
echo "SIDECAR_API_KEY=$(openssl rand -hex 32)"
```

Open `k8s/base/secret.yaml` in your editor and paste the values into the `stringData` block:

```yaml
stringData:
  DATABASE_PASSWORD: "<the POSTGRES_PASSWORD value>"
  SECRET_KEY: "<the SECRET_KEY value>"
  DATABASE_URL: "postgresql+asyncpg://glycemicgpt:<the POSTGRES_PASSWORD value>@glycemicgpt-db:5432/glycemicgpt"
  REDIS_URL: "redis://glycemicgpt-redis:6379/0"
  SIDECAR_API_KEY: "<the SIDECAR_API_KEY value>"
```

> **Don't commit `secret.yaml` with real values to a public repository.** For production deployments, use [External Secrets Operator](https://external-secrets.io/) or [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) so the actual values live in your secret manager, not in git.

### 3. Configure your domain

Open `k8s/overlays/prod/kustomization.yaml` and replace `glycemicgpt.yourdomain.com` with your actual domain in:

- The Ingress patch (`/spec/tls/.../hosts` and `/spec/rules/0/host`)
- The ConfigMap patch (`CORS_ORIGINS`)

Make sure your domain's DNS `A` record points at your cluster's ingress controller's external IP.

### 4. Configure cert-manager for HTTPS

If you don't have cert-manager installed yet:

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
kubectl wait --for=condition=Available deployment/cert-manager -n cert-manager --timeout=120s
```

Open `k8s/base/cert-manager-issuer.yaml` and set your email address (used for Let's Encrypt notifications), then apply:

```bash
kubectl apply -f k8s/base/cert-manager-issuer.yaml
```

### 5. Deploy

```bash
kubectl apply -k k8s/overlays/prod
```

This pulls the prebuilt `ghcr.io/glycemicgpt/glycemicgpt-{api,web,sidecar}:latest` images and creates everything in the `glycemicgpt` namespace.

### 6. Verify

```bash
# Watch pods come up
kubectl get pods -n glycemicgpt -w

# When everything is Running and Ready:
kubectl get svc -n glycemicgpt
kubectl get ingress -n glycemicgpt
```

You should see five Deployments / pods (`api`, `web`, `sidecar`, `db`, `redis`) and one Ingress.

### 7. Wait for the certificate

cert-manager automatically requests a Let's Encrypt certificate when the Ingress is applied. This usually takes 1-2 minutes:

```bash
kubectl get certificate -n glycemicgpt -w
```

When `READY` is `True`, you can visit `https://yourdomain.com` and see the GlycemicGPT login page.

## Updating

To pull the latest GlycemicGPT release:

```bash
# Re-apply (kustomize will redeploy any changed manifests)
kubectl apply -k k8s/overlays/prod

# Force a rollout to pick up new image versions on :latest
kubectl rollout restart deployment -n glycemicgpt
```

For a versioned deployment, edit `k8s/overlays/prod/kustomization.yaml` and pin `newTag` to a specific version (e.g. `0.4.0`) instead of `latest`.

## Building your own images

If you'd rather build the images yourself instead of using the prebuilt ones (e.g. to run a fork or a development branch), see the build instructions in [`k8s/README.md`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/k8s/README.md#2-build-and-push-images). Override `newName` in the prod overlay to point at your registry.

## Production GitOps example

For users running Flux or ArgoCD, the project lead maintains a working GitOps deployment of GlycemicGPT in their personal homelab repo: [`jlengelbrecht/prox-ops`](https://github.com/jlengelbrecht/prox-ops/tree/main/kubernetes/apps/health/glycemicgpt). It uses:

- The [`bjw-s/app-template`](https://github.com/bjw-s-labs/helm-charts/tree/main/charts/other/app-template) generic helm chart instead of plain manifests
- [CloudNativePG](https://cloudnative-pg.io/) for production-grade PostgreSQL
- An existing cluster-wide [Valkey](https://valkey.io/) (Redis-compatible) instance instead of the bundled Redis container -- isolated to a separate database number
- [External Secrets Operator](https://external-secrets.io/) instead of raw Secret manifests
- [Gateway API](https://gateway-api.sigs.k8s.io/) HTTPRoute instead of Ingress
- Network policies and security policies

That setup is more sophisticated than this guide -- it's reference material for users with similar GitOps tooling, not a recommended starting point. The plain-manifest path documented here is what most K8s users will find easier. If your cluster already runs a Redis or Valkey instance you'd prefer to reuse, see [`deploy/examples/external-redis/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/deploy/examples/external-redis) for the Docker equivalent of that pattern -- the same approach (override `REDIS_URL` to point at your existing instance) applies in K8s by editing the `glycemicgpt-secrets` Secret to set `REDIS_URL` directly and removing the bundled `redis.yaml` from `kustomization.yaml`.

## Where to learn more

- **[`k8s/README.md`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/k8s/README.md)** -- the technical reference for the manifests, including resource-limit tuning, persistent storage configuration, structured logging, automated backup operations (manual triggers, restore procedures), and detailed troubleshooting commands.
- **[`docs/dev/k8s-external-access.md`](../dev/k8s-external-access.md)** -- the developer-track guide to ingress, cert-manager, and TLS configuration.

## A helm chart is on the roadmap

The current Kustomize-based deployment works, but for users who prefer Helm a first-class chart is on the roadmap. When it lands, this page will be rewritten as a `helm install glycemicgpt` walkthrough, and the prox-ops example above will become a `values.yaml` reference. See [ROADMAP.md](../../ROADMAP.md) §Phase 1.

## Troubleshooting

If pods aren't healthy, the same starting points apply as Docker -- see [Troubleshooting](../troubleshooting/index.md). For Kubernetes-specific issues (ingress not routing, certs not provisioning, pod scheduling failures), [`k8s/README.md`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/k8s/README.md#troubleshooting) has the operational detail.

Some K8s-specific quick checks:

```bash
# Pod not starting -- check events
kubectl describe pod -n glycemicgpt <pod-name>

# Pod logs
kubectl logs -n glycemicgpt -l app.kubernetes.io/component=api -f
kubectl logs -n glycemicgpt -l app.kubernetes.io/component=sidecar -f

# Certificate stuck -- check cert-manager events
kubectl describe certificate -n glycemicgpt

# Image pull errors -- if you're using a private registry
kubectl create secret docker-registry regcred \
  --docker-server=ghcr.io \
  --docker-username=<username> \
  --docker-password=<token> \
  -n glycemicgpt
```
