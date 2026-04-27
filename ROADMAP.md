# GlycemicGPT Project Roadmap

*Phases below are sequenced, not scheduled. Development moves at the pace of the community and the project's small maintainer team; we don't commit to dates.*

This roadmap reflects the strategic direction of GlycemicGPT. It is a living document that evolves based on community feedback, contributor availability, and the needs of the diabetes community. If you want to help shape the direction of this project, [open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues), [join our Discord](https://discord.gg/TJKzjsts), or contribute directly via our [Contributing Guide](CONTRIBUTING.md).

---

## Vision

GlycemicGPT exists to ensure no one manages diabetes alone. Our goal is to build an open source, privacy-first platform that gives people with diabetes -- and the people who care for them -- AI-powered insight into their own data. The platform is a monitoring, analysis, and education tool designed to complement professional healthcare, not replace it.

---

## Current State -- Foundation (Delivered)

The core platform is live, functional, and in daily use by the project maintainer.

### Platform

- Real-time glucose monitoring via Dexcom G7 (cloud API)
- Tandem t:slim X2 and Mobi insulin pump data integration (BLE and cloud)
- AI-powered daily briefs analyzing overnight patterns, meal responses, and trends
- Conversational AI chat with RAG-backed clinical diabetes knowledge base
- BYOAI architecture supporting Claude, OpenAI, Ollama (fully local), and any OpenAI-compatible endpoint
- Configurable threshold-based alerting with caregiver escalation
- Multi-channel alert delivery (in-app, push notifications, Telegram)
- Configurable data retention (default 365 days, up to 10 years)
- Printable reports for endocrinologist appointments

### Mobile & Wearable

- Android app (Kotlin, Jetpack Compose, BLE device data reading)
- Wear OS watch face with glucose, insulin on board, and trend complications

### Infrastructure & Governance

- Self-hosted Docker Compose deployment
- Kubernetes manifests for homelab and cloud deployment
- Capability-based plugin SDK for community device data drivers
- GPL-3.0 licensing
- Governance documentation, contributing guide, code of conduct
- Medical disclaimer and safety documentation

---

## Phase 1 -- Stability & Trust

**Focus:** Harden the platform, build community confidence, and establish legal and organizational foundations.

### AI Engine 2.0

The AI layer is the heart of GlycemicGPT. This phase focuses on making it more reliable, more transparent, and more grounded in real clinical knowledge.

- Hallucination feedback mechanism -- a user-facing control to flag incorrect AI responses and force re-evaluation from a fresh session with data pulled directly from the RAG system
- Expanded RAG knowledge base -- broader clinical research coverage sourced from peer-reviewed diabetes research, NIH resources, and clinical guidelines
- Improved prompt engineering -- more personalized, data-grounded responses that reflect the user's own history and patterns
- AI evaluation framework -- internal testing pipeline to measure output quality, safety, and accuracy before changes reach users

### Platform Stability

- Mobile app authentication stability fixes
- Performance optimization for long-term data queries
- Expanded test coverage across all services
- Bug fixes driven by community feedback

### Platform Safety Enforcement Layer

Phase 1 hardens the platform's monitoring-only stance at the plugin loading boundary. The SDK is already read-only by design for therapy -- no insulin-delivery or other therapeutic write primitives, no architectural path for AI to issue such commands. (Non-therapeutic device-management operations such as connect/disconnect, unpair, and CGM calibration remain available as session and lifecycle commands.) `SafetyLimits` already validate incoming readings. Phase 1 adds active rejection at the plugin registry:

- Plugin registry rejection -- plugins declaring capabilities outside the official read-only capability set are refused at load time, regardless of build origin
- Capability-set integrity checks at startup with logging when an unknown capability is encountered
- Test coverage that asserts unknown capabilities cannot be activated by any code path
- Documentation of the enforcement boundary as a stable contract that both official and project-owned unofficial builds rely on

### Legal & Organizational

- Legal review of platform positioning relative to medical device classification
- Disclaimer and terms of use review with legal counsel
- Open Source Collective fiscal hosting approval
- Transparent financial reporting via Open Collective

---

## Phase 2 -- Ecosystem Integration

**Focus:** Meet users where they are. Integrate with the platforms the diabetes community already uses so they don't have to change their existing setup.

### Third-Party Platform Integrations

Many people with diabetes already have working setups with established tools. GlycemicGPT should enhance what they have, not ask them to replace it.

- **Nightscout** -- pull data from existing Nightscout instances for AI analysis
- **Loop** -- integration with Apple's DIY closed-loop ecosystem
- **AAPS (AndroidAPS)** -- integration for Android-based closed-loop users
- **xDrip** -- support for xDrip data streams

These integrations follow a no-touch philosophy: GlycemicGPT reads data from your existing platform and runs AI analysis on top of it. It does not modify, control, or interfere with your existing diabetes management setup.

### Device Data Support Expansion

- Additional CGM data support (Libre, Medtronic Guardian)
- Additional pump data reading (Omnipod, Medtronic)
- Community plugin development examples and tutorials for device data drivers

### AI-Enhanced Endo Reports

- AI analysis integrated into printable reports
- Pattern flags and trend anomalies highlighted for clinician review
- Summary insights designed to facilitate productive endo conversations
- Exportable formats suitable for clinical settings

---

## Phase 3 -- Mobile Expansion

**Focus:** Bring GlycemicGPT to iOS and establish official app store presence.

### iOS Development

The diabetes tech community skews heavily toward iPhone. iOS support is essential for broad adoption.

- **iOS Unofficial (Sideloaded via TestFlight)** -- open source iOS app distributed via the Browser Build method (GitHub Actions to TestFlight). Users fork the repo, add their Apple Developer credentials, and GitHub Actions compiles and delivers the app to TestFlight automatically. No Mac required. This follows the same proven distribution model used by Loop and xDrip4iOS.
- **iOS Official (App Store)** -- a streamlined, App Store-compliant version submitted through GlycemicGPT's Apple Developer account. Follows Apple's guidelines. Monitoring and analysis only.

### Android Official (Google Play)

- Play Store-compliant version alongside the existing sideloaded build
- Adheres to Google Play policies and review requirements
- Monitoring and analysis only

### Unofficial vs. Official App Distinction

The unofficial sideloaded versions (both Android and iOS) are open source and user-built from source. They include the full plugin SDK so users can extend the platform with additional device data drivers. The SDK is read-only by design across all builds; the project does not ship plugins that control insulin delivery. Users who build from source take full responsibility for their build, consistent with the DIY ethos established by projects like Loop and AndroidAPS.

The official App Store and Play Store versions are monitoring and analysis tools. They do not include the plugin SDK. They are designed to comply with platform guidelines and provide a streamlined experience for non-technical users.

### Repository Architecture

As mobile apps mature, the project will split into a multi-repo architecture so the official-vs-unofficial boundary is an organizational reality, not just a documentation distinction:

| Repository | Purpose | Plugin SDK |
|------------|---------|------------|
| `glycemicgpt` (this repo) | Backend platform, web dashboard, plugin SDK source, governance | n/a (publishes the SDK) |
| `glycemicgpt-android-unofficial` | Sideloaded Android build, extensible | Included |
| `glycemicgpt-ios-unofficial` | Sideloaded iOS build via TestFlight Browser Build, extensible | Included |
| `glycemicgpt-android-official` | Google Play build, monitoring only | Not included |
| `glycemicgpt-ios-official` | Apple App Store build, monitoring only | Not included |

The unofficial repositories operate independently from the project's fiscal host and OSC funding. Forks that add capabilities beyond data reading -- including device control or insulin delivery -- are the responsibility of the fork's users, who become the manufacturer of their personal medical device. The GlycemicGPT project does not endorse, distribute, or accept liability for such forks. See [MEDICAL-DISCLAIMER.md](MEDICAL-DISCLAIMER.md) for the legal framework.

### Wear & Watch

- Apple Watch complications (alongside existing Wear OS support)
- Unified wearable experience across platforms

---

## Phase 4 -- Intelligence & Scale

**Focus:** Move from reactive analysis to proactive prediction. Lower the barrier to entry for non-technical users.

### Predictive Analytics

Blood glucose prediction is approached with caution and transparency. Predictions will be built on deterministic mathematical models -- not LLM-based generation. The AI layer may analyze historical data to suggest parameter adjustments for human review, but prediction outputs themselves are rule-based, auditable, and explainable.

- Blood glucose trajectory prediction using insulin-on-board and carb-on-board modeling
- Predictive alerting based on forecasted glucose trends
- Trend forecasting and anomaly detection
- Clear confidence indicators on all predictions

### Hosted Service for Non-Technical Users

A managed deployment of GlycemicGPT for users who don't want to run their own infrastructure. Same monitoring-and-analysis platform, hosted by the project under transparent governance and funding.

- Self-hosted remains the primary supported path; the hosted service exists to lower the entry barrier without changing the product
- Identical feature parity with self-hosted (no hosted-only features that fragment the community)
- Transparent pricing, transparent infrastructure costs, and a clear data ownership policy
- AI provider configuration follows the same model as self-hosted (subscription tier or BYOAI)

### Accessibility & Onboarding

- Cloud deployment templates (Railway, Fly.io, one-click options)
- Unified documentation portal aggregating guides from all project repositories
- User onboarding experience for first-time setup

### Community & Sustainability

- Multi-patient caregiver dashboards (parents managing multiple T1D children)
- Expanded contributor community and mentorship
- Sustainable funding model through Open Collective and community sponsorship

---

## Guiding Principles

These principles guide every decision on the roadmap:

1. **Monitoring and analysis first.** The GlycemicGPT platform and all official app store releases are monitoring and analysis tools. They read data from diabetes devices and provide AI-powered insights. They do not control insulin delivery or modify pump settings. The unofficial sideloaded mobile apps include the read-only plugin SDK so users can extend the platform with additional device data drivers; they do not include any plugin that controls insulin delivery. The AI layer has no architectural path to a device write surface. Users who build from source and extend the platform do so at their own discretion and responsibility, consistent with the DIY ethos established by projects like Loop and AndroidAPS in the broader patient-built diabetes-tech tradition.

2. **Privacy first.** User health data stays on user-controlled infrastructure. The platform does not phone home, collect telemetry, or transmit data to GlycemicGPT or any third party.

3. **Transparency about AI limitations.** AI makes mistakes. Every AI-generated output is clearly labeled as informational. The platform never presents AI analysis as medical advice. Users are always directed to consult their healthcare team.

4. **Meet users where they are.** Integrations with existing platforms (Nightscout, Loop, AAPS, xDrip) are prioritized over requiring users to switch tools. GlycemicGPT should enhance, not replace.

5. **Open source, always.** The platform is GPL-3.0 licensed. The source code is freely available. Community contributions are welcomed and encouraged. Financial transparency is maintained through Open Collective.

---

## How to Get Involved

| I want to... | Start here |
|--------------|------------|
| Report a bug or request a feature | [Open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues) |
| Contribute code | [Contributing Guide](CONTRIBUTING.md) |
| Discuss ideas or ask questions | [Community Discord](https://discord.gg/TJKzjsts) |
| Support the project financially | [Open Collective](https://opencollective.com/glycemicgpt) |
| Build a device data plugin | [Contributing Guide](CONTRIBUTING.md#device-data-drivers) (then the [Plugin Architecture Reference](docs/plugin-architecture.md)) |

---

*Built by patients who got tired of waiting. Because no one should manage diabetes alone.*
