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

- **Frontier models** (Claude Opus, Claude Sonnet, GPT-4-class) are more accurate and less prone to hallucination
- **Smaller / cheaper models** (GPT-3.5-class, smaller Ollama models) hallucinate more, especially on diabetes-specific topics

If you're using a smaller model and seeing weird answers, switching to a frontier model often fixes it. The trade-off is cost or subscription requirements.

## How the AI knows about diabetes (RAG)

GlycemicGPT augments the model's general knowledge with a curated knowledge base of clinical diabetes research, NIH resources, and clinical guidelines. When you ask a question, the platform retrieves relevant passages from this knowledge base and includes them in the prompt to the AI. This is called retrieval-augmented generation (RAG).

This is why the AI can answer "what's a normal IoB after a meal" with reasonably accurate information even if you're using a model that wouldn't know that out-of-the-box.

The knowledge base is being expanded -- see [ROADMAP.md](../../ROADMAP.md) §Phase 1 AI Engine 2.0.

## Sessions and history

Each conversation in AI chat is a session. Sessions persist on the platform's database, so you can come back to a chat later and continue where you left off, or scroll back through previous conversations.

If a conversation gets weird or hallucinated answers, **start a new session** rather than trying to argue the AI back to reality. Fresh sessions get a fresh context window with the latest data.

## Privacy

- Your messages and the AI's responses are stored on your platform's database
- The text of your message goes to your configured AI provider (Claude, OpenAI, your local Ollama instance, etc.) -- this is unavoidable; that's what an AI provider does
- The platform does not log your AI conversations to any third-party analytics
- The platform does not use your conversations to train AI models -- that's a load-bearing privacy commitment, see [Privacy](../concepts/privacy.md)

## When the chat doesn't work

- See [AI chat isn't working](../troubleshooting/ai-chat-not-working.md) for the troubleshooting walkthrough

## On the watch (optional)

If you've installed the [Wear OS watch face](../mobile/wear-os.md), you can ask quick AI queries by long-pressing the watch face. Voice input goes through your phone's speech-to-text and the response appears on the watch. Voice chat doesn't work in the emulator -- requires a real device.
