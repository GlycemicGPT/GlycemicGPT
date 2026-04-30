---
title: BYOAI -- Bring Your Own AI
description: Why GlycemicGPT doesn't bundle an AI, and how to plug in your own.
---

GlycemicGPT does not host an AI service. You bring your own. This page explains your options, what each costs, and how to choose.

## Quick pick

If you don't want to read the whole page, here's the short version:

- **You want strongest privacy and have the hardware to run a local model** → Option 5 (local Ollama). Nothing leaves your network. Free.
- **You already pay for Claude (Pro / Max)** → Option 1. No additional cost. Best AI quality among cloud options.
- **You already pay for ChatGPT (Plus / Team)** → Option 2. No additional cost.
- **You don't have either subscription and want a vendor-supported cloud path** → Option 3 (Claude API key). Roughly $1-5/month for typical use.
- **You want the cheapest cloud path** → Option 4 (OpenAI API key with smaller models). Often under $1/month.

You can change your mind any time without losing data. Full details, cost ranges, and privacy implications for each option are below.

## Why we built it this way

Most diabetes-tech platforms that include AI either bundle a model (paying the inference cost on your behalf and passing it on as a subscription) or charge you per-message. GlycemicGPT takes a different approach: you plug in your own AI provider credential -- either an existing subscription you already pay for or an API key -- and the platform routes AI requests through it.

Three reasons:

1. **Cost transparency.** You see what you're paying for. The project doesn't mark up or skim your AI usage.
2. **Privacy.** Your AI conversations go directly between your platform and your chosen provider. The project's servers are not in the path.
3. **Choice.** You can use a premium model (Claude Opus, GPT-4-class) for the best quality, a cheaper model for cost savings, or a fully local model for maximum privacy. The platform doesn't lock you into any one provider.

## Five real options

GlycemicGPT supports five distinct ways to provide an AI credential. They differ in cost model, privacy properties, and quality.

### Option 1: Existing Claude subscription (Pro / Max)

If you already pay for Claude (a Pro or Max subscription), you can route GlycemicGPT through it -- no separate API key, no extra billing.

How it works: you run `npx @anthropic-ai/claude-code setup-token` on your computer, sign in to your Claude account in the browser, copy the token it prints, paste it into GlycemicGPT. The token authenticates as you under your existing subscription.

- **Cost:** included in your existing Claude subscription
- **Privacy:** your messages go to Anthropic. Per Anthropic's [Privacy Policy](https://www.anthropic.com/legal/privacy) and [Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms), Pro / Max conversation data is not used to train their models by default (you can verify the current state of this policy in those documents -- this page reflects our reading as of April 2026, not legal advice).
- **Quality:** Claude (Sonnet or Opus depending on your subscription tier) -- among the best models available

This is the path most users with an existing Claude subscription will choose.

### Option 2: Existing ChatGPT subscription (Plus / Team)

Same idea for OpenAI: if you already pay for ChatGPT (Plus, Team, or Enterprise), use that subscription.

`npx @openai/codex login`, sign in, get the token, paste into GlycemicGPT.

- **Cost:** included in your existing ChatGPT subscription
- **Privacy:** your messages go to OpenAI. Training-use defaults vary by plan (Plus / Team / Enterprise have different policies). Read [OpenAI's Terms of Use](https://openai.com/policies/terms-of-use) and your plan's specific terms; you can also opt out of training-use in your ChatGPT account settings.
- **Quality:** GPT-4-class via the Codex CLI

### A note on the subscription-token options (Options 1 and 2)

The Claude Code and Codex command-line tools that produce these tokens are official, vendor-published tools. Anthropic publishes `claude-code setup-token`; OpenAI publishes `codex login`. Both are designed for "you, on your laptop, running the CLI."

What's less clear-cut is using those tokens **from a third-party server** -- our AI bridge running in Docker -- to make ongoing background calls on your behalf. That's a different shape of usage than what the tokens were originally designed for, and **neither vendor has publicly endorsed or blocked this pattern.** What this means in practice:

- **It works today,** and many self-hosters use it. If it didn't work, neither this option nor any of the various "use my Claude subscription headlessly" tools floating around the community would.
- **Tokens can stop working** without notice -- if a future client update binds tokens to specific user-agent strings or client IDs, your existing token would silently start failing. If your AI chat suddenly returns auth errors, this is the most common cause; regenerate the token via the same CLI command.
- **Vendor terms of service can change.** Read [Anthropic's Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms) and [OpenAI's Terms of Use](https://openai.com/policies/terms-of-use) and decide for yourself whether you're comfortable with this usage.
- **If reliability matters** -- you depend on this for caregiver alerts, you're running it for someone whose data needs to flow continuously, you don't want a 3am surprise -- use **Option 3 or 4** (a direct Anthropic or OpenAI API key). Those are explicitly priced and supported for server-side use; tokens won't be revoked unexpectedly because the vendor specifically designed them for this use case.

If you want the strongest reliability *and* strongest privacy, **Option 5 (local Ollama)** removes the question entirely -- nothing depends on a vendor's tolerance for an unusual usage pattern.

### Option 3: Direct Claude API key

If you'd rather pay per token directly to Anthropic instead of via a subscription:

1. Sign up at [console.anthropic.com](https://console.anthropic.com)
2. Add billing
3. Create an API key (starts with `sk-ant-...`)
4. Paste it into GlycemicGPT

- **Cost:** pay per token, billed by Anthropic. Typically $3-15 per million input tokens depending on the model.
- **Privacy:** API traffic is not used for training, per [Anthropic's Commercial Terms of Service](https://www.anthropic.com/legal/commercial-terms) (different document from the consumer terms covering Options 1 / 2)
- **Quality:** any Claude model you have access to

This is the right path if you don't have a Claude subscription but want occasional API access.

### Option 4: Direct OpenAI API key

Same as Claude API key, but for OpenAI.

1. Sign up at [platform.openai.com](https://platform.openai.com)
2. Add billing
3. Create an API key (starts with `sk-...`)
4. Paste it into GlycemicGPT

- **Cost:** pay per token, billed by OpenAI
- **Privacy:** API traffic is not used for training by default, per [OpenAI's API data-usage policy](https://openai.com/enterprise-privacy) (different document from the consumer ChatGPT terms covering Option 2)
- **Quality:** any OpenAI model

### Option 5: Local model via Ollama (or any OpenAI-compatible endpoint)

If you want AI to never leave your network -- the strongest privacy stance -- run a model locally.

[Ollama](https://ollama.com) is the easiest option:

1. Install Ollama on your computer or server
2. Pull a model: `ollama pull llama3.1:8b` (or whichever model you prefer)
3. In GlycemicGPT, **Settings → AI Provider → OpenAI-compatible**:
   - Base URL: `http://localhost:11434/v1` (or your Ollama server's URL)
   - Model name: the model you pulled
   - API key: any non-empty string (Ollama doesn't check it)

This same option works for any OpenAI-compatible endpoint: LM Studio, vLLM, llama.cpp's server mode, OpenRouter, Together, Groq, etc.

- **Cost:** free if you're running on your own hardware
- **Privacy:** strongest -- nothing leaves your network. Vendor terms-of-service questions (Options 1 and 2) do not apply.
- **Quality:** depends entirely on the model you run. **The project has not yet conducted formal evals comparing local vs cloud models on diabetes-specific reasoning.** Anecdotally and based on community feedback: smaller 7B-8B models often miss nuance on insulin-action timing and pattern interpretation; mid-range 30B-class models do meaningfully better; 70B+ models are competitive with cloud frontier models but require serious hardware (24GB+ VRAM). If you're running this for live use and can't afford to be wrong, treat any local-model output the way you'd treat any AI suggestion -- as a thread to pull on, not advice to act on.

## How to choose -- detailed

The Quick pick section at the top of this page covers the common cases. For the longer version:

- **You already pay for Claude (Pro / Max)** → Option 1, no question
- **You already pay for ChatGPT (Plus / Team)** → Option 2
- **You want top quality and don't mind cloud AI** → Option 1 or 3 (Claude is the strongest for diabetes reasoning, in the project lead's experience)
- **You want low cost and don't mind cloud AI** → Option 4 (OpenAI API with cheaper models like GPT-4o-mini)
- **You want maximum privacy or fully offline operation** → Option 5 (local Ollama)
- **You're on a homelab and have GPUs to spare** → Option 5 with a top-tier local model (Llama 3.1 70B, Qwen 2.5 72B, etc.)

You can switch between options at any time without losing data. The provider only affects new AI calls; everything already saved on your platform stays.

## Why doesn't the project just host AI?

The roadmap has a "hosted service for non-technical users" item (Phase 4) -- a managed deployment of the platform itself. Even when that ships, **AI is BYOAI** -- the hosted service does not act as an AI provider.

Reasons:

1. **AI inference is expensive.** Bundling AI would mean either charging users a margin (which the project doesn't want to do) or absorbing the cost (which the project can't sustainably do)
2. **AI vendor relationships are political.** Bundling Claude or OpenAI ties the project to one provider's commercial terms; BYOAI keeps the project provider-neutral
3. **Privacy.** Routing all users' AI traffic through a single project-controlled endpoint creates a privacy bottleneck and a juicy target. BYOAI distributes the trust surface across each user's chosen provider
4. **Local models matter.** Some users want fully offline AI for legitimate reasons. A bundled-AI model would either exclude them or require maintaining a separate "self-hosted only" tier

## Privacy implications by option

| Option | Where your messages go | Used for training? | Vendor policy reference |
|---|---|---|---|
| Claude subscription | Anthropic's servers | No, per Anthropic terms for Pro / Max | [Privacy Policy](https://www.anthropic.com/legal/privacy), [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) |
| ChatGPT subscription | OpenAI's servers | Plan-dependent (opt-out available) | [OpenAI Terms of Use](https://openai.com/policies/terms-of-use) |
| Claude API key | Anthropic's servers | No | [Anthropic Commercial Terms](https://www.anthropic.com/legal/commercial-terms) |
| OpenAI API key | OpenAI's servers | No, by default | [OpenAI API privacy](https://openai.com/enterprise-privacy) |
| Local Ollama | Your network only | No (it's your machine) | n/a |

The links above are the source of truth -- if anything on this page conflicts with what those policies currently say, the policies are right and we should fix this page. Last reviewed: April 2026.

In every case, the **GlycemicGPT project does not see, log, or use any of these messages** -- the platform's AI bridge just passes them between you and your chosen provider.

## Switching providers

You can change your AI provider at any time:

1. **Settings → AI Provider** in the dashboard
2. Pick a different option, paste the new credential
3. Save

Your existing chat history, briefs, and data are unaffected. Only new AI requests use the new provider.

If you switch from a frontier model to a smaller one (e.g., Claude Sonnet → Llama 3.1 8B), expect noticeably worse AI output quality. The platform itself is the same; the AI brain behind it is different.
