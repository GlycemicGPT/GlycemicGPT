---
title: Using AI Chat
description: Ask the AI questions about your data in plain language.
---

AI chat is a conversational interface to your diabetes data. You ask questions in plain language; the AI looks at your recent glucose, insulin, and patterns and responds with observations.

> **AI suggestions are not medical advice.** Treat them as informational starting points -- something to talk about with your endocrinologist, not something to act on directly. The AI also makes mistakes -- it's a language model, not a doctor.

## Where to find it

In the dashboard, click **AI Chat** in the navigation.

## What to ask

Some questions the AI can usefully answer:

- *"Why was my glucose high after dinner last night?"*
- *"Show me times when I went low this week."*
- *"How does my Time in Range compare this week to last week?"*
- *"Are there patterns in when I miss boluses?"* (if you've been using the platform long enough for patterns to show)
- *"Summarize my last three days for me."*
- *"What questions should I ask my endo at my next appointment?"*

The AI has access to your glucose, insulin, and pump data on the platform. It does not have access to your medical records, prescription history, or anything outside what flows through GlycemicGPT.

## What it won't / shouldn't answer

The AI is configured to refuse / deflect on:

- **Specific dosing recommendations** (e.g., "should I take 3 units now") -- always defers to your healthcare provider
- **Diagnostic claims** -- it won't tell you you're insulin-resistant or have a specific complication; it will surface patterns and suggest you discuss with your doctor

If you ask something that needs your doctor, expect the AI to say so explicitly.

## How accurate is the AI?

Depends on the model you've configured (see [Get Started -- Step 8](../get-started.md#step-8-configure-your-ai-provider)). In general:

- **Premium models** (Claude Opus, Claude Sonnet, GPT-4-class) are more accurate and less likely to make things up
- **Smaller / cheaper models** (GPT-3.5-class, smaller Ollama models) get more wrong answers, especially on diabetes-specific topics

If you're using a smaller model and seeing weird answers, switching to a premium model often fixes it. The trade-off is cost or subscription requirements.

## How the AI knows about diabetes

**Today's runtime behavior:** when you ask a question, the platform passes your own glucose, insulin, and pump data to the AI alongside your message. The AI then reasons over *your* history plus its general training. This is the main mechanism keeping answers anchored to your real situation right now.

**The architecture also includes a retrieval-augmented generation (RAG) layer** -- a vector store, retrieval pipeline, and trust-tier system designed to pull relevant clinical references into the prompt alongside your data. The architecture is in place; **what's not yet shipped is a populated curated library** (see below). Once content is loaded, AI answers will be grounded in vetted clinical references in addition to your own data.

### Honest status of the knowledge base today

The RAG infrastructure exists -- the vector store, the retrieval pipeline, the trust-tier system that distinguishes authoritative references from user-provided notes. **What's not yet shipped is a populated curated library.** Today's deployments effectively run with the AI reasoning from the model's general training plus your data, with the curated layer pending.

This means:

- The architecture supports adding clinical references (ADA Standards of Care, ISPAD pediatric guidelines, peer-reviewed research, etc.) and is designed for it
- The actual seed-data load is on the roadmap -- see [ROADMAP.md](../../ROADMAP.md) §Phase 1 AI Engine 2.0
- For now, treat AI answers about *general diabetes facts* with the same skepticism you'd apply to any LLM answer; AI answers about *your own data* benefit from the data being passed in directly with your question

If there's a specific reference you'd like to see prioritized for the curated library, [open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) with the citation.

## AI is non-deterministic, and what we do about it

A useful framing if you're new to AI tools in healthcare contexts: **AI models are non-deterministic.** Unlike traditional software that gives the same output for the same input every time, an AI can give you slightly different answers to the same question on different days, or for different users with similar data. They can also generate confident-sounding answers that are wrong -- the failure mode usually called *hallucination*.

This is a real property of the technology. It can't be eliminated; it can be mitigated. Here's how GlycemicGPT addresses it today, and what we're doing next:

**Today, our mitigations:**

- **Your data is sent with every question.** The AI doesn't rely on memory of "what your numbers usually are" -- it sees your actual data each time. This grounds answers in real history.
- **RAG retrieval (architecture in place; curated content rolling out).** As the curated library lands, AI answers to clinical-reference questions will pull from authoritative sources alongside your data. The trust-tier system distinguishes authoritative content from user-provided notes.
- **Strong scope guardrails in the prompt.** The platform's system prompt explicitly instructs the AI not to give specific dosing recommendations or diagnostic claims, and to defer to your healthcare team. This won't catch every failure mode, but it shapes the typical response.
- **Fresh sessions for fresh problems.** When a conversation gets weird, starting a new session is a reset that often fixes it -- the AI gets a clean view of your latest data without the prior conversation's context drift.

**On the roadmap:**

- **A hallucination-feedback mechanism** so you can flag a bad answer in the UI, have the platform regenerate from a clean session, and contribute the flagged exchange back to the project (with your consent and your data redacted). This builds an evaluation set over time we can use to measure model quality on diabetes-relevant reasoning. See [ROADMAP.md](../../ROADMAP.md) §Phase 1 AI Engine 2.0.
- **Curated knowledge base population** as described above -- moving from "RAG architecture exists" to "RAG architecture is loaded with vetted clinical references."
- **Internal evaluations on diabetes-specific reasoning** -- the project has not yet conducted formal evals comparing model quality on common diabetes questions. Building this is on the roadmap; until we have it, we can't make precise quality claims.
- **Source attribution in AI responses** -- when answers cite the curated library, surfacing the underlying source so you can read the reference yourself.

**Bottom line:** AI is a thread to pull on, not a source of truth. The platform is designed to give you the AI's reasoning in a frame that makes follow-up easy (a chat session you can interrogate further) rather than as final-answer pronouncements. If an AI answer about your own pattern doesn't match what you observe, trust your observation and flag it -- that feedback is how the system improves.

This is why the AI can answer "what's a normal IoB after a meal" with reasonably accurate information even if you're using a model that wouldn't know that out-of-the-box.

The knowledge base is being expanded -- see [ROADMAP.md](../../ROADMAP.md) §Phase 1 AI Engine 2.0.

## Sessions and history

Each conversation in AI chat is a session. Sessions persist on the platform's database, so you can come back to a chat later and continue where you left off, or scroll back through previous conversations.

If a conversation gets weird or wrong answers, **start a new session** rather than trying to argue the AI back to reality. AI models have a limited amount of conversation they can hold in mind at once -- starting fresh gives the model a clean slate with the latest data.

## Privacy

- Your messages and the AI's responses are stored on your platform's database
- The text of your message goes to your configured AI provider (Claude, OpenAI, your local Ollama instance, etc.) -- this is unavoidable; that's what an AI provider does
- The platform does not log your AI conversations to any third-party analytics
- The platform does not use your conversations to train AI models -- that's a load-bearing privacy commitment, see [Privacy](../concepts/privacy.md)

## When the chat doesn't work

- See [AI chat isn't working](../troubleshooting/ai-chat-not-working.md) for the troubleshooting walkthrough

## On the watch (optional)

If you've installed the [Wear OS watch face](../mobile/wear-os.md), you can ask quick AI queries by long-pressing the watch face. Voice input goes through your phone's speech-to-text and the response appears on the watch. Voice chat doesn't work in the emulator -- requires a real device.
