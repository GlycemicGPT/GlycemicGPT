---
title: AI chat isn't working
description: AI chat is stuck loading, returns errors, or doesn't respond.
---

You opened AI chat in the dashboard, asked something, and it never responded -- or it returned an error. AI chat goes through a handful of components; this page walks them in order.

## How AI chat works

When you send a message in AI chat, this happens:

1. The browser sends your message to the **API** service
2. The API forwards it to the **AI bridge** (a small service that lives between the API and whichever AI provider you set up)
3. The AI bridge uses your configured AI provider credential (subscription token or API key) to call the actual AI provider (Claude, OpenAI, Ollama, etc.)
4. The AI provider responds; the AI bridge returns the response to the API; the API streams it back to the browser

A failure can happen at any step.

> The AI bridge runs as a service named `sidecar` (or `ai-sidecar`) inside Docker, so when you see those names in commands below, that's what we're talking about.

## Step 1: Is your AI provider configured?

In the dashboard, **Settings → AI Provider** -- you should see a configured provider. If it says **No provider configured**, that's the issue. See [Get Started -- Step 8: Configure your AI provider](../get-started.md#step-8-configure-your-ai-provider) for the per-provider walkthrough.

If a provider is configured but you're not sure it's working, click **Test connection**. The dashboard tries a small request to the provider and reports back.

## Step 2: Is the AI bridge running?

```bash
docker compose ps
```

Look for the `sidecar` (or `ai-sidecar`) service -- that's the AI bridge. If it's not `healthy`, AI chat won't work because the API can't reach it.

```bash
docker compose logs --tail=100 sidecar
```

Common AI bridge issues:

- **The service exits immediately on start** -- often a missing `SIDECAR_API_KEY` env var. Check `.env`.
- **"no Claude token configured" error** when you try to chat -- you set up the Claude API key but the AI bridge wasn't restarted to pick it up. Run `docker compose restart sidecar`.

## Step 3: Is your provider credential still valid?

Provider credentials can expire or be revoked.

### Subscription tokens (Claude / ChatGPT)

The OAuth tokens from `npx @anthropic-ai/claude-code setup-token` and `npx @openai/codex login` are long-lived but **do expire** if you sign out of your provider account, change your password, or hit "revoke all tokens" in the provider's settings.

If chat suddenly stopped working after you signed in to Claude or ChatGPT somewhere else, regenerate the token:

1. Run the setup command again on your computer (`npx @anthropic-ai/claude-code setup-token` or `npx @openai/codex login`)
2. Copy the new token
3. In GlycemicGPT, **Settings → AI Provider**, paste the new token

### API keys (Anthropic / OpenAI)

If you regenerated or revoked your API key in the provider's console, the old one stops working. Get a new one and re-paste:

- Claude: [console.anthropic.com](https://console.anthropic.com) → API Keys
- OpenAI: [platform.openai.com](https://platform.openai.com) → API keys

### API keys: rate limits and credits

Direct API keys can fail because:
- **No credit on the account** -- both Anthropic and OpenAI require pre-purchased credit. Check your billing dashboard.
- **Rate limit hit** -- temporary, retry in a few minutes.

Check the AI bridge logs for the actual error from the provider:

```bash
docker compose logs --tail=50 sidecar
```

## Step 4: Local models (Ollama / OpenAI-compatible)

If you're using Ollama or a local OpenAI-compatible endpoint:

### Is the Ollama server actually running?

```bash
curl http://localhost:11434/api/tags
```

If this returns a list of installed models, Ollama is running. If you get connection refused, start it.

### Can the platform reach Ollama?

If Ollama is on the same computer as the platform, the Base URL in your AI Provider config needs to be reachable from inside Docker. `http://localhost:11434/v1` from inside a Docker container does NOT mean "the host's localhost" -- it means the container's own localhost.

Use one of:
- `http://host.docker.internal:11434/v1` (macOS / Windows Docker Desktop)
- `http://172.17.0.1:11434/v1` (Linux Docker default bridge)
- The host's actual LAN IP, e.g. `http://192.168.1.50:11434/v1`

### Does the model name match what you have installed?

```bash
ollama list
```

The model name in your AI Provider config (e.g. `llama3.1:8b`) must match exactly. `llama3` and `llama3.1:8b` are different models from Ollama's perspective.

## Step 5: AI chat hangs forever / never responds

If the message just sits there and nothing happens (no error, no response):

- **Check the AI bridge logs** in real time: `docker compose logs -f sidecar`
- **Check API logs**: `docker compose logs -f api`
- Send a test message and watch for activity

Common causes:
- **Streaming issue** -- some browsers and proxies break Server-Sent Events. Try a different browser to rule it out.
- **Caddy / Cloudflare timeout** -- if you're on an always-on deployment, the layer in front of your platform that handles HTTPS (Caddy on a VPS, or Cloudflare Tunnel) has a default request-timeout that can cut off long AI responses. Caddy's default is generous (5 minutes); Cloudflare's free-tier limit is 100 seconds. If a long answer keeps getting cut off, that's likely the cause.
- **AI provider just being slow** -- Anthropic and OpenAI both occasionally have slow days. Check their status pages: [status.anthropic.com](https://status.anthropic.com), [status.openai.com](https://status.openai.com).

## Step 6: AI chat returns wrong / weird answers

Different problem class -- the AI is responding, just not well.

This is typically not a "broken" issue, it's an AI quality issue. Things that help:

- **Use a stronger model.** Free / cheap models hallucinate more. Claude Opus and GPT-4-class models are stronger on diabetes-relevant reasoning than smaller models.
- **Don't treat it as medical advice.** AI suggestions should never be acted on for medical decisions without consulting your healthcare team. The platform labels every AI response as informational, not advice.
- **Report bad outputs.** GlycemicGPT will (per ROADMAP §Phase 1) ship a hallucination-feedback mechanism so you can flag bad answers and have the AI re-evaluate from a fresh session with data pulled directly from RAG.

## Still stuck?

Capture this and bring it to [Discord](https://discord.gg/QbyhCQKDBs):

```bash
docker compose logs --tail=50 api sidecar
```

Plus:
- Which AI provider option you're using (Claude subscription / OpenAI subscription / Claude API / OpenAI API / Ollama)
- The error message you see in the dashboard (if any)
