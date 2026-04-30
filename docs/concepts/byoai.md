---
title: BYOAI -- Bring Your Own AI
description: Why GlycemicGPT doesn't bundle an AI, and how to plug in your own.
---

GlycemicGPT does not host an AI service. You bring your own. This page explains your options, what each costs, and how to choose.

## Quick pick

If you don't want to read the whole page, here's the short version:

- **You want strongest privacy and have the hardware to run a local model** → Option 5 (local AI). Nothing leaves your network. Free.
- **You already pay for Claude (Pro / Max)** → Option 1. No additional cost. Best AI quality among cloud options.
- **You already pay for ChatGPT (Plus / Team)** → Option 2. No additional cost.
- **You don't have either subscription and want a vendor-supported cloud path** → Option 3 (Claude API key) or Option 4 (OpenAI API key). You pay per token directly to the vendor.
- **You want one credential that works across many models** → Option 5 also covers OpenAI-compatible router services like [OpenRouter](https://openrouter.ai/) (untested by the project but should work since it speaks the OpenAI-compatible API).

> **Honest note on cost:** GlycemicGPT's actual usage cost on the API-key options depends on how often you use AI chat, how long your conversations get, how many briefs you generate, and which model you pick. The project has not yet measured this in a way we can publish a credible "$X/month" number. Smaller / cheaper models cost less, premium models cost more, but the meaningful number is "your usage on your model." Set a billing limit on your Anthropic / OpenAI account and watch it for the first month if cost matters.

You can change your mind any time without losing data. Full details, privacy implications, and the subscription-token reliability discussion are below.

## Why we built it this way

GlycemicGPT routes AI requests through a credential **you provide** -- either an existing subscription you already pay for, an API key, an AI router service like OpenRouter, or a local model running on your own hardware. The project itself does not host or charge for AI.

Three reasons:

1. **Cost transparency.** You see what you're paying for. The project doesn't mark up or skim your AI usage.
2. **Privacy.** Your AI conversations go directly between your platform and your chosen provider. The project's servers are not in the path.
3. **Choice.** You can use a premium cloud model (Claude Opus, GPT-4-class), a cheaper model for cost savings, an AI router for access to many models with one credential, or a fully local model for maximum privacy. The platform doesn't lock you into any one provider.

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

- **Cost:** pay per token, billed by Anthropic. Anthropic's per-million-token rates vary by model (current rates on [Anthropic's pricing page](https://www.anthropic.com/pricing)). What this means in practice for GlycemicGPT depends entirely on your usage -- the project hasn't yet measured typical monthly cost in a publishable way. Set a billing alert on your Anthropic console and watch the first month if cost matters.
- **Privacy:** API traffic is not used for training, per [Anthropic's Commercial Terms of Service](https://www.anthropic.com/legal/commercial-terms) (different document from the consumer terms covering Options 1 / 2)
- **Quality:** any Claude model you have access to

This is the right path if you don't have a Claude subscription but want occasional API access.

### Option 4: Direct OpenAI API key

Same as Claude API key, but for OpenAI.

1. Sign up at [platform.openai.com](https://platform.openai.com)
2. Add billing
3. Create an API key (starts with `sk-...`)
4. Paste it into GlycemicGPT

- **Cost:** pay per token, billed by OpenAI. OpenAI's per-million-token rates vary by model (current rates on [OpenAI's pricing page](https://openai.com/api/pricing/)). Same caveat as the Claude API option -- the project hasn't yet measured typical GlycemicGPT cost; set a billing alert and watch the first month.
- **Privacy:** API traffic is not used for training by default, per [OpenAI's API data-usage policy](https://openai.com/enterprise-privacy) (different document from the consumer ChatGPT terms covering Option 2)
- **Quality:** any OpenAI model

### Option 5: OpenAI-compatible endpoint (local model, AI router, or any compatible server)

This option points GlycemicGPT at any URL that speaks the OpenAI Chat Completions API. Common uses:

**Run a fully local model on your own hardware** -- the strongest privacy stance, since nothing leaves your network. Several mature options:

- **[Ollama](https://ollama.com)** -- the easiest local-model server. `ollama pull <model>`, then point GlycemicGPT at `http://localhost:11434/v1`.
- **[LM Studio](https://lmstudio.ai/)** -- GUI-driven; easier on Windows / macOS for users new to local AI.
- **[vLLM](https://docs.vllm.ai/)** / **[llama.cpp server](https://github.com/ggerganov/llama.cpp)** -- for users who want maximum performance / control.
- **[Text Generation Inference (TGI)](https://github.com/huggingface/text-generation-inference)** -- HuggingFace's serving stack.

**Use an AI router service** -- one credential, access to many models, OpenAI-compatible API.

- **[OpenRouter](https://openrouter.ai/)** is the best-known option. You'd paste an OpenRouter API key here and pick whichever model you want (Claude, GPT, Llama, Mistral, Qwen, others). **Note: OpenRouter is not actively tested by the project**, but since it speaks the OpenAI-compatible API, it should work. If you try it and hit issues, [file an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) -- official support is on the table once we know what users are actually doing here.
- Other router services (Together, Groq, etc.) follow the same pattern. Same caveat: they should work, but aren't tested.

**To configure**, go to **Settings → AI Provider → OpenAI-compatible** and set:

- **Base URL** -- the endpoint URL (e.g. `http://localhost:11434/v1` for Ollama, `https://openrouter.ai/api/v1` for OpenRouter)
- **Model name** -- whichever model the endpoint exposes
- **API key** -- if the endpoint requires one (router services do; local servers usually don't, but the field still requires any non-empty string)

**Properties of this option:**

- **Cost:** free for local models running on your own hardware. Router services charge per token (rates vary by provider).
- **Privacy:** strongest for local models -- nothing leaves your network. Router services have their own privacy / training policies; check them.
- **Quality:** depends on the model. **The project has not yet conducted formal evals on what local model size produces reliable results for GlycemicGPT's use cases.** Community feedback so far suggests smaller (7B-8B) models miss nuance on insulin-action timing and pattern interpretation, but we don't yet have a recommended minimum or a measured "this model does well, this one doesn't" list. If you have hardware to run something in the 13B-30B range, that's a reasonable starting point to experiment from -- and please report what works back to the project. Treat any local-model output the way you'd treat any AI suggestion -- as a thread to pull on, not advice to act on.

## Realistic cost ranges

The project has not yet conducted formal cost telemetry, so the numbers below are **rough estimates** based on token-pricing math and observed usage patterns. Treat them as ballpark, not a guarantee. Pricing on the vendor side also changes -- always confirm against the linked pricing pages.

### What drives cost on Options 3 and 4 (direct API keys)

Two things consume tokens in GlycemicGPT:

- **Daily briefs.** Each brief packages your previous day's data and asks the AI to write a summary. The data payload alone can be 5K-20K input tokens depending on how much glucose / insulin / pump data you have for the day; the AI response is typically 1K-2K output tokens. **One brief per day is the default.**
- **AI chat.** Each chat turn includes your message, the conversation history, your current data context, and the AI's response. A short single-turn question might use 5K-15K input + 500 output tokens. A long multi-turn conversation with deep context-pulls can run 30K-100K+ input tokens by the end. **This is the bigger swing factor by far.**

If RAG retrieval ever becomes populated (currently architecture-only), each request will also include the retrieved reference chunks -- adding maybe 5K-15K input tokens per request.

### Approximate monthly ranges (single user, US pricing)

These are **order-of-magnitude estimates only**. Do your own math against [Anthropic's pricing](https://www.anthropic.com/pricing) and [OpenAI's pricing](https://openai.com/api/pricing/).

| Usage profile | Cheap models (GPT-4o-mini, Haiku) | Mid-tier (Sonnet, GPT-4o) | Premium (Opus, GPT-4) |
|---|---|---|---|
| **Briefs only, no chat** (1 brief/day) | under $1/month | $1-5/month | $5-15/month |
| **Light** (1 brief/day, ~5 short chat turns/day) | $1-5/month | $5-20/month | $20-60/month |
| **Average** (1 brief/day, ~15 chat turns/day with multi-turn conversations) | $3-10/month | $15-50/month | $50-150/month |
| **Heavy** (multiple briefs, deep multi-turn AI chat sessions, frequent re-asks) | $10-30/month | $50-150/month | **$150-400+/month** |

**The "few cents to a few dollars" framing earlier versions of these docs used was misleading** -- it's true at the very low end of the table, but only there. A realistic adult-T1 user who actually engages with the AI features regularly can absolutely spend $20-100+ per month on direct API usage. If that matters to your decision, the **subscription paths (Options 1 and 2) cap your cost** at your subscription price -- which is why they're the recommendation when you have one.

### What about the subscription options (1 and 2)?

Your existing Claude Pro / Max or ChatGPT Plus / Team subscription includes a usage allowance -- routing GlycemicGPT through it consumes that same allowance. You don't pay anything extra for the AI; you may, on heavy usage days, hit your subscription's rate limits earlier than you would just chatting with Claude / ChatGPT manually. Subscription paths give you predictable cost (the monthly subscription price, no surprises) but unpredictable headroom (limits aren't published in detail and Anthropic / OpenAI tune them).

### What about local models (Option 5)?

Free at the API layer -- you only pay for the electricity and hardware to run the model. The trade-off is quality (smaller models miss more nuance) and hardware investment (a strong local model needs serious VRAM).

### Concrete recommendation if cost matters

1. Set a hard billing limit on your Anthropic or OpenAI account at a number you're comfortable with (e.g., $25/month) **before** plugging the API key in.
2. Run for the first month and watch the actual usage in your provider's billing dashboard.
3. Adjust: pick a cheaper model, scale back AI chat usage, or move to a subscription path if you find you're hitting your limit.

This is more honest than us guessing for you. AI pricing moves; your usage patterns are personal; the only number that matters is what *you* spend.

## How to choose -- detailed

The Quick pick section at the top of this page covers the common cases. For the longer version:

- **You already pay for Claude (Pro / Max)** → Option 1, no question
- **You already pay for ChatGPT (Plus / Team)** → Option 2
- **You want top quality and don't mind cloud AI** → Option 1 or 3 (Claude is the strongest for diabetes reasoning, in the project lead's experience)
- **You want maximum privacy or fully offline operation** → Option 5 with a local server (Ollama, LM Studio, vLLM, llama.cpp, etc.)
- **You're on a homelab and have GPU headroom** → Option 5 with the largest model your hardware can comfortably run
- **You want one credential that works across many models / providers** → Option 5 pointed at an AI router service like OpenRouter (untested but should work)

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
| Local model (Option 5) | Your network only | No (it's your machine) | n/a |
| AI router (Option 5, e.g. OpenRouter) | The router's servers, then forwarded to the underlying model provider | Depends on the router and the model -- read the router's policy AND the upstream model provider's policy | Provider-specific |

The links above are the source of truth -- if anything on this page conflicts with what those policies currently say, the policies are right and we should fix this page. Last reviewed: April 2026.

In every case, the **GlycemicGPT project does not see, log, or use any of these messages** -- the platform's AI bridge just passes them between you and your chosen provider.

## Switching providers

You can change your AI provider at any time:

1. **Settings → AI Provider** in the dashboard
2. Pick a different option, paste the new credential
3. Save

Your existing chat history, briefs, and data are unaffected. Only new AI requests use the new provider.

If you switch from a frontier model to a smaller one (e.g., Claude Sonnet → Llama 3.1 8B), expect noticeably worse AI output quality. The platform itself is the same; the AI brain behind it is different.
