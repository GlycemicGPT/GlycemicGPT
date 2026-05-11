---
title: Knowledge base
description: How GlycemicGPT grounds AI answers in trusted sources you control, and why the project never ships clinical content.
---

GlycemicGPT's AI doesn't answer your questions from "what the model already knows." It answers from a small library of trusted reference material attached to your account — your **knowledge base**. This page explains what's in there, where it comes from, what GlycemicGPT will and won't put in it on your behalf, and how you control it.

## Quick summary

- Your knowledge base is a per-account collection of trusted reference material the AI can pull from when answering you.
- The project itself **never ships clinical content** — no glycemic targets, no insulin dosing data, no treatment guidance. We don't author medical opinions.
- Clinical content reaches your AI through paths **you control**: documents you upload, URLs you tell the AI it's allowed to fetch from, and a future feature where the AI proposes additions for your approval.
- You can see and manage everything in the dashboard at `/dashboard/knowledge-base` and `/dashboard/settings/research-sources`.

## Why a knowledge base at all

Generic AI models hallucinate, especially on niche clinical topics. "What's the ADA target for time in range?" can return an answer that's plausible-sounding but wrong, or based on out-of-date guidelines, or simply made up.

Retrieval-Augmented Generation (RAG) fixes this by giving the AI a small, curated reference library to consult before answering. When you ask "what's a normal time in range target?", the AI:

1. Searches your knowledge base for relevant entries
2. Pulls the most relevant snippets into its context
3. Answers based on those snippets, citing them in the response

The quality of the answer depends entirely on what's in the knowledge base. Garbage in, garbage out — which is why GlycemicGPT cares so much about *who* gets to put things in.

## The four trust tiers

Every entry in your knowledge base is tagged with one of four trust tiers. The tier determines how the AI weighs the entry, whether it gets passed through a prompt-injection filter, and who's responsible for its accuracy.

### `AUTHORITATIVE` — ecosystem and technical reference

Project-shipped content covering the open-source diabetes ecosystem itself: how Loop's algorithm works, how AAPS structures its data, the difference between Nightscout and Nocturne, what file formats Tidepool accepts. **This tier never contains clinical guidance.** It's documentation about *software* and *integration*, not about *health*.

This is the only tier the project itself contributes to. The content is written or indexed by maintainers and reviewed under the `apps/api/knowledge/**` CODEOWNERS rule.

If you're wondering "why does the AI need to know how AAPS works?" — the answer is that GlycemicGPT positions itself as an AI layer for the OSS diabetes ecosystem. Your AI being able to talk fluently about Loop, AAPS, OpenAPS etc. is core to that.

### `RESEARCHED` — clinical content the AI fetched on your behalf

Content the AI fetched from URLs **you configured** as approved research sources. The AI can only research from sources you've added.

You manage your research sources at `/dashboard/settings/research-sources`. Typical entries: ADA Standards of Care URLs, FDA drug labels, manufacturer documentation for your CGM or pump. The AI fetches these on a schedule (default weekly), chunks them, embeds them, and stores them in this tier.

**Project's stance:** we don't ship a list of "official sources" the AI uses by default. You curate the list. The AI never adds a source on its own — though a future feature (see below) will let the AI *propose* sources or content for your approval.

### `USER_PROVIDED` — documents you uploaded

Anything you upload through `/dashboard/knowledge-base`: PDFs of your endocrinologist's notes, a CGM training booklet, a paper your friend recommended, your own personal cheat sheet of pump settings. Per-account, never shared with other users.

This is the most direct path: you have a document you trust, you upload it, the AI can reference it.

### `EXTRACTED` — facts pulled from your chat history

When you tell the AI things in conversation ("my carb ratio is 1:12 in the morning, 1:10 at lunch"), it can extract those as standalone facts and store them so future conversations have context. Per-account; you can see and delete anything in the knowledge-base dashboard.

## What the project does and does not put in your knowledge base

| Does | Does not |
|---|---|
| Ship ecosystem documentation as `AUTHORITATIVE` (Loop algorithm, AAPS internals, Nightscout API mappings) | Ship clinical content of any kind |
| Provide the pipeline that fetches from your configured research sources | Pre-populate research sources with the project's recommendations |
| Run the prompt-injection filter on `RESEARCHED` and lower-tier content | Auto-add clinical content the AI found via background research without your approval |
| Let you upload documents directly to `USER_PROVIDED` | Decide what your glycemic targets, dosing data, or treatment thresholds should be |

This is a deliberate liability and trust boundary. **GlycemicGPT is not a medical authority.** Pre-shipping content like "the ADA TIR target is greater than 70%" would put the project on the hook for clinical accuracy every time the ADA updates a guideline, and would inject our restatement into every conversation about your time in range, regardless of whether your situation actually fits the standard target. That's the wrong place for clinical opinion to come from. Yours, your endocrinologist's, and explicitly-cited official sources you trust — that's the right place.

## How you manage your knowledge base

Three places in the dashboard:

### `/dashboard/knowledge-base`

Lists every chunk in your knowledge base across all four tiers. Filters by tier, source, search by content. You can see exactly what the AI has access to. Delete anything you no longer want the AI to reference.

### `/dashboard/settings/research-sources`

Where you tell the AI which URLs it's allowed to research from. Add, edit, remove sources. The AI fetches from these on a schedule and stores findings in the `RESEARCHED` tier.

Best practice: only add URLs you've personally vetted as trustworthy. The AI will faithfully read whatever is at the URL — if you point it at a dubious blog, you'll get dubious content in your knowledge base.

### Document upload

Inside the knowledge-base page, an upload control accepts PDFs, plain text, and markdown. Files are chunked, embedded, and stored as `USER_PROVIDED`. Per-account.

## Coming soon: AI-proposed additions with your approval

A planned feature (tracked internally as Epic 45) will close the gap between "the AI knows about your settings" and "the AI knows what's likely to be useful for someone like you."

The rough flow:

1. You configure your platform settings — pump model, insulin type, CGM, target ranges, etc.
2. The AI uses those settings as context for background research from your approved source list.
3. When the AI finds something it thinks would be valuable to add — and only from sources you've already approved — it doesn't auto-add. It validates the source, drafts a "proposed addition" with rationale.
4. You get an alert: "the AI wants to add X to your knowledge base because Y."
5. You review in the dashboard. Approve → the chunk lands in your `RESEARCHED` tier and the AI can reference it. Reject → it's discarded and the AI learns not to propose similar content.

Critical guarantees this feature will preserve:

- **The AI never auto-adds anything.** Every proposed addition requires your explicit approval.
- **The AI never researches from sources outside your approved list** without first asking you to add them as a source (which you can decline).
- **You can revoke approval.** Anything previously approved can be deleted from the knowledge base.

This feature is not yet implemented. The current state of the world is: clinical content arrives only via `USER_PROVIDED` uploads or scheduled fetches from your existing approved `ResearchSource` list.

## What about caregivers?

Caregivers see the patient's knowledge base if the patient has granted that scope (see `/docs/caregivers/`). Caregivers cannot add or remove content on the patient's behalf — only the patient (or platform admin) can curate the knowledge base. Caregiver visibility is read-only.

When the AI-proposed-additions feature lands, the alert for approval can optionally route to a configured caregiver — but the caregiver can only acknowledge the alert; the actual approve/reject decision still belongs to the patient.

## Privacy implications

Knowledge-base content is stored in the platform's database alongside your account. It is not shared with the AI provider as training data — it's only sent inline as context for the specific question you're asking.

If you delete a chunk, it's soft-deleted (marked `valid_to`) and excluded from future retrieval. Hard-delete via account deletion follows your platform's data retention settings.

For more on privacy posture across the platform, see [Privacy](/docs/concepts/privacy).

## Frequently asked

### Why doesn't the AI just know diabetes guidelines like the ADA targets out of the box?

It would, from its training data — but training data is frozen at some past date and the AI would happily quote a 2022 target like it's current. Worse, when the AI quotes from training data it doesn't cite anything, so you can't verify. The knowledge base solves both: cited sources, and you choose what's current.

### Can I add a URL that requires login?

Not yet. The research pipeline currently handles public URLs only. Authenticated sources are on the roadmap.

### What happens if I delete a `ResearchSource`?

Existing `RESEARCHED` chunks from that source stay in your knowledge base (you'll still see them in the dashboard) but won't be refreshed. Delete the chunks separately if you don't want them retained.

### How big can my knowledge base get?

Per-user retention follows your platform's data retention settings. The retrieval pipeline is bounded — only the most relevant top-k chunks per query reach the AI, regardless of total knowledge-base size.

### Where can I see exactly what the AI saw when answering a question?

Future admin tooling will surface this; for now it's only visible in the API logs.
