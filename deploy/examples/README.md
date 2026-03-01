# Deployment Examples

Self-contained Docker Compose examples for different deployment scenarios.

## Which example should I use?

| Scenario | Example | TLS | Notes |
|----------|---------|-----|-------|
| Local development | Root [`docker-compose.yml`](../../docker-compose.yml) | No | Run from repo root with `docker compose up --build -d` |
| Server with a domain | [`prod-caddy/`](prod-caddy/) | Automatic (Let's Encrypt) | Recommended for most users |
| Already using Cloudflare | [`cloudflare-tunnel/`](cloudflare-tunnel/) | Cloudflare-managed | Zero exposed ports |
| Existing Redis/Valkey cluster | [`external-redis/`](external-redis/) | Depends on proxy | No bundled Redis |

## Quick start

```bash
# Pick an example
cd deploy/examples/prod-caddy

# Create your .env from the template
cp .env.example .env

# Generate secrets -- paste each output into .env
echo "SECRET_KEY:          $(openssl rand -hex 32)"
echo "POSTGRES_PASSWORD:   $(openssl rand -hex 32)"
echo "REDIS_PASSWORD:      $(openssl rand -hex 32)"

# Edit .env with the generated values above,
# update your domain in CORS_ORIGINS and Caddyfile, then:
docker compose up -d
```

## Generating secrets

Use `openssl` to generate cryptographically random secrets:

```bash
openssl rand -hex 32
```

You need separate values for:
- `SECRET_KEY` -- API session signing
- `POSTGRES_PASSWORD` -- database access
- `REDIS_PASSWORD` -- Redis authentication (prod examples)

## External Redis / Valkey

Any example can use an external Redis instance. Remove the `redis` service from the compose file and set `REDIS_URL` directly:

```env
REDIS_URL=redis://:<your-redis-password>@your-redis-host:6379/0
```

Compatible with Redis 7+, Valkey 7+, AWS ElastiCache, and any Redis-protocol-compatible store.

For TLS connections, use the `rediss://` scheme:

```env
REDIS_URL=rediss://:<your-redis-password>@redis.example.com:6380/0
```

## CORS for mobile app

The mobile app connects directly to the API (not through the web frontend). If you use the mobile app, add your domain to `CORS_ORIGINS`:

```env
CORS_ORIGINS=["https://glycemicgpt.example.com"]
```

## Kubernetes

These examples target Docker Compose. For Kubernetes:

- Use the container images directly (`ghcr.io/jlengelbrecht/glycemicgpt-{api,web,sidecar}`)
- Point `REDIS_URL` at your cluster's Redis/Valkey service
- Use Kubernetes Secrets for `SECRET_KEY`, `POSTGRES_PASSWORD`, etc.
- Add an Ingress resource with TLS termination (cert-manager, etc.)
- The `external-redis/` example is the closest starting point

## Bring your own reverse proxy

If you use Nginx, Traefik, HAProxy, or another proxy instead of Caddy:

1. Start from the `external-redis/` example (or any prod example)
2. Expose the `web` service port (3000) to your proxy network
3. Configure your proxy to forward HTTPS traffic to `web:3000`
4. Add `Strict-Transport-Security` headers on the proxy (the API sets other security headers itself)
5. Next.js handles `/api/*` proxying to the backend internally -- your proxy only needs to talk to the web service
