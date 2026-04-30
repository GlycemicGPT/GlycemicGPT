---
title: Acknowledgments
description: The projects, people, and prior art that GlycemicGPT stands on.
---

GlycemicGPT exists because of work that came before it. This page acknowledges the projects whose code, research, or community advocacy directly inform what's shipping here. None of the projects below are affiliated with GlycemicGPT; we're listing them because their work made ours possible.

## Pump and CGM library credits

This project's diabetes-device integrations are built on top of -- or directly informed by -- several MIT-licensed open-source libraries. The categorization below distinguishes "runtime dependency" (we ship and consume the library directly) from "architectural reference" (we studied the work to build our own, no code is imported).

### James Woglom ([@jwoglom](https://github.com/jwoglom))

Three of jwoglom's open-source projects directly inform our Tandem support:

- **[pumpX2](https://github.com/jwoglom/pumpx2)** -- *architectural reference, not a runtime dependency.* Java library implementing a reverse-engineered Bluetooth protocol for Tandem t:slim X2 / Mobi pumps. GlycemicGPT's Tandem mobile-app driver is an independent Kotlin port informed by pumpX2's protocol documentation, opcodes, message formats, and EC-JPAKE authentication flow. We do not import pumpX2; we use its test vectors to validate parser correctness in our own code. Crediting this work is required by the MIT license and matters: without pumpX2's published reverse-engineering, this project's pump driver would not exist.
- **[controlX2](https://github.com/jwoglom/controlx2)** -- *architectural reference, not a runtime dependency.* Android / Wear OS reference app built on pumpX2. We studied its BLE service lifecycle, reconnection state machines, and pairing flow patterns. No code is imported.
- **[tconnectsync](https://github.com/jwoglom/tconnectsync)** -- ***runtime dependency.*** Python library for talking to Tandem's t:connect cloud (`TandemSourceApi`). Consumed via `apps/api/pyproject.toml` as `tconnectsync>=2.3.0`. Used by `tandem_sync.py` (cloud download) and for OAuth token acquisition in `tandem_upload.py` (cloud upload).

All three are MIT-licensed by James Woglom. Per-library attribution lives in:

- [`apps/mobile/THIRD_PARTY_LICENSES.md`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/apps/mobile/THIRD_PARTY_LICENSES.md) -- mobile-side credit for pumpX2 and controlX2 (architectural references)
- [`apps/api/THIRD_PARTY_LICENSES.md`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/apps/api/THIRD_PARTY_LICENSES.md) -- API-side credit for tconnectsync (runtime dependency)

In-source headers also reference the upstream MIT license in the relevant Tandem driver files (`TandemProtocol.kt`, `JpakeAuthenticator.kt`, `EcJpake.kt`, `Hkdf.kt`).

If you're using GlycemicGPT's Tandem integration, you're benefiting from years of jwoglom's reverse-engineering work. We are deeply grateful and try to credit accurately. If anything on this page or in the per-package license files reads as inadequate or wrong, please [open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) -- correctness matters.

### Gage Benne ([@gagebenne](https://github.com/gagebenne))

- **[pydexcom](https://github.com/gagebenne/pydexcom)** -- ***runtime dependency.*** Python library for fetching glucose data from Dexcom's cloud using the user's Dexcom account credentials (the same path the official Dexcom Follow / Clarity apps use). Consumed via `apps/api/pyproject.toml` as `pydexcom>=0.2.0`. Used by `apps/api/src/services/dexcom_sync.py` on a polling schedule.

MIT-licensed by Gage Benne. Credit lives in [`apps/api/THIRD_PARTY_LICENSES.md`](https://github.com/GlycemicGPT/GlycemicGPT/blob/main/apps/api/THIRD_PARTY_LICENSES.md).

## The diabetes-OSS movement

GlycemicGPT is part of a much larger #WeAreNotWaiting tradition that has been building open-source diabetes tools collaboratively since around 2013. The projects below predate this one by years; in many cases by a decade. We're listed alongside them, not above them.

- **[Nightscout](https://nightscout.github.io/)** -- the open-source CGM dashboard that effectively defined the "self-host your own diabetes data" pattern. The fact that this is even a category that exists is because of Nightscout. The maintainers and the [Nightscout Foundation](https://www.nightscoutfoundation.org/) deserve credit for building and sustaining the movement that GlycemicGPT slots into.
- **[OpenAPS](https://openaps.org/)** and Dana Lewis -- the project that started the closed-loop branch of #WeAreNotWaiting. GlycemicGPT does not do closed-loop and never will, but the broader tradition of "T1s building safety-critical software for themselves" comes from here.
- **[Loop](https://loopkit.github.io/loopdocs/)** and the LoopKit / Pete Schwamb -- the iOS closed-loop project that brought thousands of T1s and parents into the DIY closed-loop world. GlycemicGPT respects the legal and architectural posture (forks-as-personal-medical-device) that Loop established.
- **[AndroidAPS / AAPS](https://androidaps.readthedocs.io/)** -- the Android closed-loop project that supports the broadest pump matrix in the open-source space. The plugin architecture in GlycemicGPT's mobile app borrows conceptual framing from AAPS's pump-driver model.
- **[xDrip+](https://github.com/NightscoutFoundation/xDrip)** -- the Android CGM relay-and-dashboard that supports more sensors than anything else. The "what should a CGM-companion app on Android even look like" question is largely answered by xDrip+; we benefit from the answer.
- **[Tidepool](https://www.tidepool.org/)** -- a nonprofit cloud platform for uploading and reporting on diabetes data, and the FDA-cleared variant of Loop ([Tidepool Loop](https://www.tidepool.org/tidepool-loop)). The "free, open, vendor-neutral diabetes data layer" pattern is something GlycemicGPT learns from.

## AI

The AI features in GlycemicGPT depend on AI providers we do not run. The "BYOAI" model means the AI brain behind any answer comes from one of:

- **[Anthropic](https://www.anthropic.com/)** (Claude family) -- whose Claude Code CLI we use as the OAuth path for subscription tokens
- **[OpenAI](https://openai.com/)** (GPT family) -- whose Codex CLI we use as the OAuth path for ChatGPT subscriptions
- **[Ollama](https://ollama.com/)** and the open-weights model ecosystem (Meta Llama, Qwen, Mistral, etc.) -- which makes fully local AI viable for self-hosters with sufficient hardware

The retrieval-augmented generation layer also depends on publicly available diabetes clinical literature -- the [American Diabetes Association Standards of Care](https://diabetesjournals.org/care/issue/47/Supplement_1), peer-reviewed research indexed via NIH / PubMed, and similar sources. Specific source listing for the RAG layer is in [How AI chat works](../daily-use/ai-chat.md#how-the-ai-knows-about-diabetes).

## Project lead's note

This project would not be possible without the work above. If you've contributed to any of the listed projects and feel your work should be called out differently, please reach out -- correctness here matters more than concision.

If you're a T1 or caregiver who got value out of any of the upstream projects, please consider contributing back to them as well. The diabetes-OSS world stays alive because users contribute time, code, and donations to it -- the [Nightscout Foundation](https://www.nightscoutfoundation.org/donate) in particular accepts donations and sustains a lot of the infrastructure the rest of us build on.
