# Deploying GlycemicGPT

## Architecture

```
[Reverse Proxy]  -->  [Web (Next.js :3000)]  -->  [API (FastAPI :8000)]  -->  [PostgreSQL]
     HTTPS                                              |                      [Redis]
                                                        v
                                                 [AI Sidecar :3456]
```

- **Web** serves the frontend and proxies `/api/*` requests to the backend.
- **API** handles all business logic, auth, and data.
- **AI Sidecar** manages AI provider connections (BYOAI).
- **Redis** is used for rate limiting, session cache, and SSE pub/sub.
- A **reverse proxy** (Caddy, Nginx, Cloudflare Tunnel, etc.) terminates TLS. You bring your own.

## Quick start (development)

```bash
# From the repository root:
docker compose up --build -d

# Verify:
curl http://localhost:8000/health
curl http://localhost:3000
```

The root `docker-compose.yml` is the dev compose file -- no separate example needed.

## Production checklist

Before deploying to production:

- [ ] **TLS termination** -- set up a reverse proxy with HTTPS. See [examples](examples/).
- [ ] **Generate secrets** -- unique values for `SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`:
  ```bash
  openssl rand -hex 32
  ```
- [ ] **Redis password** -- set `REDIS_PASSWORD` in your `.env`. The prod compose files use `requirepass` automatically.
- [ ] **No default credentials** -- the prod compose files use `?` syntax to require secrets (they fail to start if missing).
- [ ] **Backups** -- set up PostgreSQL backups (`pg_dump` or volume snapshots).
- [ ] **CORS origins** -- if using the mobile app, add your domain to `CORS_ORIGINS`.
- [ ] **Firewall** -- only expose ports 80/443 (or use a tunnel with zero exposed ports).

## Deployment examples

| Example | Description |
|---------|-------------|
| [`examples/prod-caddy/`](examples/prod-caddy/) | Caddy with automatic Let's Encrypt HTTPS |
| [`examples/cloudflare-tunnel/`](examples/cloudflare-tunnel/) | Cloudflare Tunnel (zero exposed ports) |
| [`examples/external-redis/`](examples/external-redis/) | External Redis/Valkey (no bundled Redis) |
| Root `docker-compose.yml` | Local development (no TLS, no passwords) |

Each example includes a `docker-compose.yml` and `.env.example`. See [`examples/README.md`](examples/README.md) for details.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes (prod) | `change-me-...` (dev) | API session signing key |
| `POSTGRES_PASSWORD` | Yes (prod) | `glycemicgpt` (dev) | Database password |
| `REDIS_PASSWORD` | Recommended | (none) | Redis `requirepass` value |
| `REDIS_URL` | No | `redis://redis:6379/0` | Full Redis URL (overrides bundled Redis) |
| `IMAGE_TAG` | No | `latest` | Container image version |
| `CORS_ORIGINS` | No | `[]` | JSON array of allowed CORS origins |
| `SIDECAR_API_KEY` | No | (none) | Shared key between API and AI sidecar |
| `ALLOW_PRIVATE_AI_URLS` | No | `true` | Set `false` for cloud deployments to block private-network AI URLs |
| `LOG_FORMAT` | No | `json` | `json` or `text` |

## Updating

```bash
# Pull latest images
docker compose -f docker-compose.prod.yml pull

# Restart with new images
docker compose -f docker-compose.prod.yml up -d
```

Or pin a specific version:

```bash
IMAGE_TAG=0.5.0 docker compose -f docker-compose.prod.yml up -d
```
