# GlycemicGPT Kubernetes Deployment

This directory contains Kubernetes manifests for deploying GlycemicGPT to a Kubernetes cluster.

## Prerequisites

- Kubernetes cluster (v1.25+)
- kubectl configured to access your cluster
- kustomize (built into kubectl v1.14+)
- Container images built and pushed to a registry

## Directory Structure

```
k8s/
├── base/                    # Base manifests
│   ├── kustomization.yaml   # Kustomize configuration
│   ├── namespace.yaml       # GlycemicGPT namespace
│   ├── configmap.yaml       # Non-sensitive configuration
│   ├── secret.yaml          # Sensitive data (template)
│   ├── postgres.yaml        # PostgreSQL database + PVC
│   ├── redis.yaml           # Redis cache
│   ├── api.yaml             # FastAPI backend
│   ├── web.yaml             # Next.js frontend
│   ├── ingress.yaml         # Ingress for external access
│   ├── backup-cronjob.yaml  # Database backup CronJob
│   └── nodeport-services.yaml # Alternative: NodePort access
└── overlays/
    ├── dev/                 # Development overlay
    │   └── kustomization.yaml
    └── prod/                # Production overlay
        └── kustomization.yaml
```

## Quick Start

### 1. Configure Secrets

Edit `k8s/base/secret.yaml` and replace placeholder values:

```bash
# Generate a secure secret key
openssl rand -base64 32
```

Update the following in `secret.yaml`:
- `DATABASE_PASSWORD`: Strong password for PostgreSQL
- `SECRET_KEY`: Random string for session encryption
- `DATABASE_URL`: Update password in connection string

### 2. Build and Push Images

```bash
# Build images
docker build -t glycemicgpt-api:latest ./apps/api
docker build -t glycemicgpt-web:latest ./apps/web

# Tag for your registry (example with ghcr.io)
docker tag glycemicgpt-api:latest ghcr.io/yourusername/glycemicgpt-api:latest
docker tag glycemicgpt-web:latest ghcr.io/yourusername/glycemicgpt-web:latest

# Push to registry
docker push ghcr.io/yourusername/glycemicgpt-api:latest
docker push ghcr.io/yourusername/glycemicgpt-web:latest
```

### 3. Deploy

**Development:**
```bash
kubectl apply -k k8s/overlays/dev
```

**Production:**
```bash
# Update image references in overlays/prod/kustomization.yaml first
kubectl apply -k k8s/overlays/prod
```

**Base (no overlay):**
```bash
kubectl apply -k k8s/base
```

### 4. Verify Deployment

```bash
# Check pods
kubectl get pods -n glycemicgpt

# Check services
kubectl get svc -n glycemicgpt

# Check ingress
kubectl get ingress -n glycemicgpt

# View logs
kubectl logs -n glycemicgpt -l app.kubernetes.io/component=api -f
```

## Resource Limits

Default resource allocation per component:

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| API       | 250m        | 2000m     | 512Mi          | 2Gi          |
| Web       | 100m        | 1000m     | 256Mi          | 1Gi          |
| PostgreSQL| 100m        | 500m      | 256Mi          | 1Gi          |
| Redis     | 50m         | 200m      | 64Mi           | 256Mi        |

**Total minimum:** ~500m CPU, ~1Gi RAM
**Total limits:** ~4 CPU, ~4.5Gi RAM

## Access Methods

### Option 1: Ingress (Recommended)

Configure your DNS to point `glycemicgpt.local` (or your domain) to your ingress controller.

Edit `k8s/base/ingress.yaml`:
- Change `host: glycemicgpt.local` to your domain
- Update `ingressClassName` if not using nginx
- Configure TLS for HTTPS

### Option 2: NodePort

For homelabs without an ingress controller:

1. Uncomment `nodeport-services.yaml` in `k8s/base/kustomization.yaml`
2. Apply the manifests
3. Access via:
   - API: `http://<node-ip>:30800`
   - Web: `http://<node-ip>:30300`

### Option 3: Port Forward (Development)

```bash
# API
kubectl port-forward -n glycemicgpt svc/glycemicgpt-api 8000:8000

# Web
kubectl port-forward -n glycemicgpt svc/glycemicgpt-web 3000:3000
```

## Health Checks

The API exposes health endpoints for Kubernetes probes:

| Endpoint       | Purpose          | Checks                    |
|----------------|------------------|---------------------------|
| `/health/live` | Liveness probe   | Process is running        |
| `/health/ready`| Readiness probe  | DB and Redis connected    |
| `/health`      | Full health      | Complete status           |

## Persistent Storage

PostgreSQL uses a PersistentVolumeClaim for data storage:

- **Development:** 1Gi
- **Production:** 50Gi

Configure your storage class in `postgres.yaml` if needed:
```yaml
spec:
  storageClassName: your-storage-class
```

## TLS/HTTPS

To enable HTTPS:

1. Create a TLS secret:
```bash
kubectl create secret tls glycemicgpt-tls \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key \
  -n glycemicgpt
```

2. Uncomment the TLS section in `ingress.yaml` or use the prod overlay.

For automatic certificates, consider using cert-manager:
```yaml
annotations:
  cert-manager.io/cluster-issuer: letsencrypt-prod
```

## Structured Logging

GlycemicGPT uses structured JSON logging with correlation IDs for request tracing.

### Log Format

Logs are output as JSON with the following fields:

| Field          | Description                              |
|----------------|------------------------------------------|
| `timestamp`    | ISO 8601 timestamp with timezone         |
| `level`        | Log level (INFO, ERROR, etc.)            |
| `service`      | Service name (glycemicgpt-api)           |
| `message`      | Log message                              |
| `correlation_id` | UUID for request tracing               |
| `logger`       | Logger name                              |

### Configuration

Configure logging via environment variables:

| Variable       | Default           | Description                    |
|----------------|-------------------|--------------------------------|
| `LOG_FORMAT`   | `json`            | Log format: `json` or `text`   |
| `LOG_LEVEL`    | `INFO`            | Log level                      |
| `SERVICE_NAME` | `glycemicgpt-api` | Service name in logs           |

### Viewing Logs

```bash
# Stream API logs
kubectl logs -n glycemicgpt -l app.kubernetes.io/component=api -f

# Parse JSON logs with jq
kubectl logs -n glycemicgpt -l app.kubernetes.io/component=api | jq .

# Filter by correlation ID
kubectl logs -n glycemicgpt -l app.kubernetes.io/component=api | jq 'select(.correlation_id == "your-id")'
```

## Database Backups

Automated PostgreSQL backups run via Kubernetes CronJob.

### Backup Configuration

| Variable              | Default        | Description                      |
|-----------------------|----------------|----------------------------------|
| `BACKUP_SCHEDULE`     | `0 2 * * *`    | Cron schedule (daily at 2 AM)    |
| `BACKUP_PATH`         | `/backups`     | Backup storage directory         |
| `BACKUP_RETENTION_DAYS` | `7`          | Days to keep old backups         |

### Manual Backup

```bash
# Trigger a backup manually
kubectl create job --from=cronjob/glycemicgpt-backup manual-backup-$(date +%s) -n glycemicgpt

# Check backup job status
kubectl get jobs -n glycemicgpt

# View backup logs
kubectl logs -n glycemicgpt -l app.kubernetes.io/component=backup
```

### Restore from Backup

```bash
# Copy backup from PVC to local machine
kubectl cp glycemicgpt/glycemicgpt-api-<pod>:/backups/glycemicgpt_YYYYMMDD_HHMMSS.sql.gz ./backup.sql.gz

# Restore to database
gunzip -c backup.sql.gz | kubectl exec -i -n glycemicgpt deploy/glycemicgpt-db -- psql -U glycemicgpt -d glycemicgpt
```

### Backup Storage

Backups are stored in a dedicated PVC (`glycemicgpt-backup-pvc`):
- **Default:** 5Gi
- Configure in `backup-cronjob.yaml` or via overlay

## Troubleshooting

### Pods not starting

```bash
# Check pod status
kubectl describe pod -n glycemicgpt <pod-name>

# Check events
kubectl get events -n glycemicgpt --sort-by=.metadata.creationTimestamp
```

### Database connection issues

```bash
# Check if database is ready
kubectl exec -n glycemicgpt -it deploy/glycemicgpt-db -- pg_isready -U glycemicgpt

# Check API logs
kubectl logs -n glycemicgpt -l app.kubernetes.io/component=api
```

### Image pull errors

Ensure your images are pushed to the registry and the cluster has access:
```bash
# For private registries, create an image pull secret
kubectl create secret docker-registry regcred \
  --docker-server=ghcr.io \
  --docker-username=<username> \
  --docker-password=<token> \
  -n glycemicgpt
```

## Cleanup

```bash
# Delete all resources
kubectl delete -k k8s/base

# Or delete namespace (removes everything)
kubectl delete namespace glycemicgpt
```
