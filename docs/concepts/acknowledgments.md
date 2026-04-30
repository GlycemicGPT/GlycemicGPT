---
title: Acknowledgments
description: The projects, people, and prior art that GlycemicGPT stands on.
---

GlycemicGPT exists because of work that came before it. This page acknowledges the projects whose code, research, or community advocacy directly inform what's shipping here. None of the projects below are affiliated with GlycemicGPT; we're listing them because their work made ours possible.

## Pump and CGM reverse-engineering

The Tandem Bluetooth integration in GlycemicGPT's mobile app is built on top of, or directly informed by, several open-source projects -- in particular, the years of Bluetooth reverse-engineering work done by the controlX2 / pumpX2 community.

- **[pumpX2](https://github.com/jwoglom/pumpx2)** by [@jwoglom](https://github.com/jwoglom) and contributors -- a Java library for talking to Tandem t:slim X2 / Mobi pumps over Bluetooth Low Energy. The opcodes, packet formats, and authentication flow that GlycemicGPT's Tandem driver uses are directly informed by pumpX2's documentation and source. Without this work the project's mobile-app pump driver would not exist.
- **[controlX2](https://github.com/jwoglom/controlx2)** -- the Android / Wear OS app built on top of pumpX2. Provided the practical reference for how a Tandem-targeting Android app handles BLE pairing, reconnection, and stream parsing in the real world.
- **[tconnectsync](https://github.com/jwoglom/tconnectsync)** -- the Tandem t:connect cloud sync library used by GlycemicGPT's backend to fetch pump history when the cloud path is configured.
- **[pydexcom](https://github.com/gagebenne/pydexcom)** -- the Python Dexcom Share library used by GlycemicGPT's backend to pull glucose data from Dexcom's cloud.

If you're using GlycemicGPT's Tandem integration, you're using the work of the pumpX2 contributors. We are deeply grateful and try to credit accurately. If anyone reading this thinks our use of these libraries should be called out differently or more prominently, please [open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose).

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
