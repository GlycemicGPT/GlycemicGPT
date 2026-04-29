# External Redis (or Valkey)

This example runs GlycemicGPT against an existing Redis or Valkey instance you already operate, instead of bundling Redis as part of the compose stack.

**Use this when:** you have a homelab or production cluster where Redis / Valkey is already a shared service, and you want GlycemicGPT to plug into it instead of standing up its own instance.

**You're not the audience for this example if:** you don't already run a Redis or Valkey cluster -- the bundled Redis in the other examples (root `docker-compose.yml`, `public-cloud/`, `cloudflare-tunnel/`) is simpler and works fine.

## What's different from the other examples

This compose file omits the bundled `redis` service entirely. The `api` service expects you to point it at your external instance via `REDIS_URL` in `.env`.

You'll need to provide your own reverse proxy if you want HTTPS, or combine this with one of the other examples (`prod-caddy/` for Caddy + Let's Encrypt, `cloudflare-tunnel/` for Cloudflare-managed TLS).

## Steps

### 1. Configure `.env`

```bash
cp .env.example .env
```

Set:

| Variable | What to put |
|---|---|
| `REDIS_URL` | A full URL pointing at your Redis or Valkey instance, with auth if required. Examples: `redis://:yourpassword@valkey.example.com:6379/0` (single-instance with password) or `redis://valkey.cache.svc.cluster.local:6379/2` (in-cluster Valkey on a specific database number) |
| `POSTGRES_PASSWORD` | A strong password (run `openssl rand -hex 32`) |
| `SECRET_KEY` | Generate with `openssl rand -hex 32` |

### 2. Start the stack

```bash
docker compose up -d
```

The platform will use your external Redis/Valkey for sessions, rate limiting, and SSE pub/sub.

### 3. Add a reverse proxy (your choice)

This example doesn't include one. Either:

- Combine with [`prod-caddy/`](../prod-caddy/) -- copy its `Caddyfile` and `caddy` service definition into this compose
- Combine with [`cloudflare-tunnel/`](../cloudflare-tunnel/) -- add the `cloudflared` service from that example
- Run your own existing reverse proxy (nginx, Traefik) and point it at port 3000 of the `web` service

If you're not sure, the other examples are easier starting points -- come back to this one only if you specifically need to reuse an existing Redis/Valkey.

## Why isolate by database number?

Most Redis / Valkey instances support 16 databases (numbered 0-15) within a single instance. Multiple applications can share an instance by using different databases. Set `REDIS_URL` to use a database number specific to GlycemicGPT (e.g., `/2`) so it doesn't collide with other apps on the same Redis.

## Privacy

GlycemicGPT uses Redis for session tokens and ephemeral cache only -- no clinical data lives in Redis long-term. Even so, the data passing through is sensitive (auth tokens, real-time glucose pub/sub messages). Make sure your external Redis is appropriately secured (TLS, password, network isolation) -- the platform inherits whatever security posture your Redis has.

## See also

- [Install with Docker](../../../docs/install/docker.md) for the full menu of deployment options
- [`public-cloud/`](../public-cloud/) for the recommended cloud deployment with bundled Redis and automatic HTTPS
- The same "use my existing Redis" pattern in Kubernetes is documented in [`docs/install/kubernetes.md`](../../../docs/install/kubernetes.md) -- override `REDIS_URL` in the secret and remove `redis.yaml` from the kustomization
