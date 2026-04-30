# GlycemicGPT Project Roadmap

*Phases below are sequenced, not scheduled. Development moves at the pace of the community and the project's small maintainer team; we don't commit to dates.*

This roadmap reflects the strategic direction of GlycemicGPT. It is a living document that evolves based on community feedback, contributor availability, and the needs of the diabetes community. If you want to help shape the direction of this project, [open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues), [join our Discord](https://discord.gg/QbyhCQKDBs), or contribute directly via our [Contributing Guide](CONTRIBUTING.md).

---

## Vision

GlycemicGPT exists to ensure no one manages diabetes alone. Our goal is to build an open source, privacy-first platform that gives people with diabetes -- and the people who care for them -- AI-powered insight into their own data. The platform is a monitoring, analysis, and education tool designed to complement professional healthcare, not replace it.

---

## Current State -- Foundation (Delivered)

The core platform is live, functional, and in daily use by the project lead.

### Platform

- Real-time glucose monitoring via Dexcom G7 (cloud API)
- Tandem t:slim X2 and Mobi insulin pump data integration (BLE and cloud)
- AI-powered daily briefs analyzing overnight patterns, meal responses, and trends
- Conversational AI chat with RAG-backed clinical diabetes knowledge base
- BYOAI architecture supporting Claude, OpenAI, Ollama (fully local), and any OpenAI-compatible endpoint
- Configurable threshold-based alerting with caregiver escalation
- Multi-channel alert delivery -- in-app and push notifications are the primary channels; Telegram bot integration is in alpha (implemented, not actively maintained, scheduled for a polish-or-sunset decision in Phase 3)
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

## Ongoing -- Community Feedback & Bug Fixes

**This is not a phase. It runs perpetually.**

GlycemicGPT is shipped software, used by real people managing real chronic disease, and inevitably has bugs. Listening to early-adopter feedback and fixing the things people actually run into is a permanent project commitment, not a one-time stability push relegated to a single phase.

What this commitment looks like in practice:

- **User-reported bugs are prioritized over speculative work.** A real "this broke for me on Safari" report outranks a roadmap item for a feature nobody has asked for. We finish the bug, then return to phase work.
- **The bug backlog is public.** All known bugs and broken features live on the [GitHub issue tracker](https://github.com/GlycemicGPT/GlycemicGPT/issues) under the `bug` label. We do not silently archive issues without explanation.
- **Fix decisions are explained.** When we close an issue as won't-fix, deferred, or duplicate, we say why -- so users can decide whether to escalate, fork, or work around.
- **Discord support feeds the tracker.** Live problem-solving in the Discord [#support channel](https://discord.gg/QbyhCQKDBs) results in tracker issues for anything reproducible. Problems do not live only on Discord and disappear.
- **Security and data-loss bugs interrupt phase work.** A bug that loses user data, exposes credentials, breaks the platform's monitoring-only safety stance, or otherwise causes harm gets fixed immediately, regardless of what phase work is in flight.

This commitment applies underneath every phase below. A roadmap that does not include "we will keep fixing what you tell us is broken" is not a credible roadmap. The phased work below describes the project's *direction*; the bug-fix commitment describes its *posture*.

To report a bug: [open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) with reproduction steps, your deployment environment, and (with sensitive values redacted) relevant log output.

---

## Phase 1 -- Stability & Trust

**Focus:** Harden the platform, build community confidence, and establish legal and organizational foundations.

### AI Engine 2.0

The AI layer is the heart of GlycemicGPT. This phase focuses on making it more reliable, more transparent, and more grounded in real clinical knowledge.

- Hallucination feedback mechanism -- a user-facing control to flag incorrect AI responses and force re-evaluation from a fresh session with data pulled directly from the RAG system
- Expanded RAG knowledge base -- broader clinical research coverage sourced from peer-reviewed diabetes research, NIH resources, and clinical guidelines
- Improved prompt engineering -- more personalized, data-grounded responses that reflect the user's own history and patterns
- AI evaluation framework -- internal testing pipeline to measure output quality, safety, and accuracy before changes reach users
- **Knowledge-adaptive response profiles** -- the AI adjusts its communication based on the user's comfort level with diabetes management. An experienced patient who understands carb ratios, correction factors, and insulin timing receives data-dense analysis. A newly diagnosed patient or non-clinical caregiver receives a simplified, plain-language explanation. Configurable per user through profile settings.

### Platform Stability

- Mobile app authentication stability fixes
- Performance optimization for long-term data queries
- Expanded test coverage across all services
- Bug fixes driven by community feedback
- **First-class Kubernetes install via helm chart** -- the platform deploys to Kubernetes today via the bundled Kustomize manifests, but a helm chart is the more familiar path for users running Flux or ArgoCD. Phase 1 ships a chart that wraps the existing manifests, with `values.yaml` defaults that mirror the production setup the project lead runs in their homelab.

### Platform Safety Enforcement Layer

Phase 1 hardens the platform's monitoring-only stance at the plugin loading boundary. The SDK is already read-only by design for therapy -- no insulin-delivery or other therapeutic write primitives, no architectural path for AI to issue such commands. (Non-therapeutic device-management operations such as connect/disconnect, unpair, and CGM calibration remain available as session and lifecycle commands.) `SafetyLimits` already validate incoming readings. Phase 1 adds active rejection at the plugin registry:

- Plugin registry rejection -- plugins declaring capabilities outside the official read-only capability set are refused at load time, regardless of build origin
- Capability-set integrity checks at startup with logging when an unknown capability is encountered
- Test coverage that asserts unknown capabilities cannot be activated by any code path
- Documentation of the enforcement boundary as a stable contract that both official and project-owned unofficial builds rely on

### Behavioral Pattern Detection

The platform should go beyond glucose threshold alerts to surface behavioral patterns the user and their care team may want visibility into. The platform describes what the data shows; it does not diagnose, judge, or recommend medical action.

- **Glucose-excursion-without-bolus patterns** -- detect recurring instances where glucose spikes occur without a corresponding bolus event in the same window. The platform surfaces the pattern as data; the user (and their care team) decides what it means. The platform does not infer the cause (a missed meal-time bolus, an unrecorded bolus, illness, stress, hormonal shifts, or any other reason).
- **Recurring pattern identification** -- surface time-of-day, day-of-week, or situational patterns in glucose control (e.g., consistently high readings every weekday at lunch or every weekend morning)
- **Pattern-aware alerting** -- alerts include historical context: "This is the third glucose excursion this week without a bolus event in the same window" rather than just "glucose is high"

### Documentation Infrastructure

Clear, accessible documentation is critical for adoption. Early adopter feedback confirmed that users struggle to get the platform running when docs are written for developers rather than for the people who need the tool.

- **Unified documentation portal** -- aggregate docs into a single, searchable documentation site at glycemicgpt.org/docs. As repositories split out per Phase 3, each maintains its own `/docs` folder as the source of truth, and the website build pipeline pulls and renders them into a cohesive experience.
- **Audience-first documentation** -- rewrite setup and usage guides from the perspective of a diabetic or caregiver, not a developer. Lead with what the user wants to accomplish, not how the code works.
- **Mobile app requirements** -- make the dependency on the Android companion app clear and prominent in all getting started guides, both on the website and in the GitHub README
- **Step-by-step deployment guides** -- clear, tested walkthroughs for Docker Compose, Kubernetes, and cloud deployment (Railway, Fly.io) with expected outcomes at each step
- **Troubleshooting guide** -- common issues and fixes based on real user feedback, starting with lessons from initial deployment

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

### Pump Report Ingestion (Adoption Path for Users Without Direct Integration)

A meaningful share of pump users -- particularly those not in the closed-loop / DIY-tooling space -- do not want continuous direct device integration. They use their pump's official mobile app, generate official pump reports from the vendor's portal (Tandem t:connect, Omnipod's portal, Medtronic CareLink, etc.), and want a way to get analysis of those reports without changing their day-to-day workflow.

This adoption path lets GlycemicGPT meet those users where they already are.

**The flow:**

1. User deploys the GlycemicGPT backend and turns on the integration for their pump vendor (Tandem, Omnipod, Medtronic, Dana, etc.) from Settings → Integrations
2. The integration authenticates with the vendor's portal using the user's existing credentials -- the same credentials they use to access their own pump reports
3. On a configurable schedule (daily by default; configurable from 6h to 7d), GlycemicGPT fetches the official pump reports the vendor publishes -- the same artifacts the user's endocrinologist would receive
4. The platform parses the reports into the same structured internal data model used by direct integrations (boluses, basal patterns, settings changes, alarms, IoB samples)
5. Dashboards, AGP views, TIR statistics, and the bolus-review table populate from the parsed report data
6. The AI engine analyzes the report data, surfaces patterns, and feeds findings into the RAG system so the AI chat can answer questions grounded in the report-derived events

**Why this matters:**

- **Lowers the barrier of entry substantially.** Users do not need to pair their pump to GlycemicGPT's mobile app over Bluetooth, configure cloud-upload impersonation, or modify their existing day-to-day pump workflow at all. They configure the integration once and the platform pulls and analyzes their reports automatically on the schedule they pick.
- **Reaches users outside the closed-loop community.** Many pump users follow their endocrinologist's recommended workflow (use the official app, share reports at appointments) and have no interest in DIY device integration. This path serves them without asking them to change anything.
- **Operates as a pure analysis layer.** GlycemicGPT becomes a data-analysis surface on top of the pump vendor's authoritative reports -- spotting trends and surfacing considerations to discuss with the medical team, without changing how data is collected or transmitted.
- **Adoption-driven growth.** Direct device integration has a high friction floor (BLE pairing, mobile app installation, ongoing maintenance). Pump-report ingestion has a much lower one (configure credentials, done). This is the path most likely to bring new users into the project.

**Initial vendor scope:**

- **Tandem t:connect** -- already partially supported via the existing direct cloud integration; expand to fetch the vendor's published clinician-facing reports rather than just the event stream
- **Insulet Omnipod** (DASH and 5) -- via the Omnipod portal
- **Medtronic CareLink** -- via the CareLink portal (Medtronic 5xx / 7xx series)
- **Dana RS / Dana-i** -- via the SOOIL portal where available
- **Accu-Chek Combo** -- via Roche's reporting portal where available

Each integration requires reverse-engineering the vendor's report-portal API (similar in shape to the existing Tandem cloud work), which is meaningful per-vendor engineering investment. Vendors are added in priority order driven by community demand and engineering bandwidth.

**Cross-cutting work touched by this path:**

Implementation is not a single feature -- it touches:

- **Storage** -- a unified internal model for report-derived events alongside direct-integration events, so the rest of the platform doesn't need to know the source of each data point
- **Dashboard rendering** -- treating report-derived data as a first-class data source in glucose / TIR / AGP / bolus-review components
- **AI engine** -- incorporating report-derived events into RAG and pattern-detection logic so the AI can reason over them the same way it reasons over directly-integrated data
- **Settings UI** -- per-vendor integration cards with credential entry, schedule configuration, last-sync status, and manual trigger
- **Background scheduler** -- per-user, per-integration schedule management with backoff handling for vendor-side outages and rate limiting
- **Logging and operations** -- visibility into what was pulled, when, and any vendor-side errors, with redaction of sensitive payload contents

**Scope and tradeoffs:**

- This path is **lower fidelity than direct integration.** Reports are typically generated daily or on-demand, so dashboard data isn't real-time. Live alerts are not possible from this path alone -- users wanting live alerts continue to need the direct CGM integration (and the direct pump BLE integration if they want live IoB and reservoir).
- This path is **complementary, not competing,** with direct integration. A common pattern: direct CGM integration for live glucose, report ingestion for the pump side instead of pairing the pump over Bluetooth.
- Vendor-side report APIs are not officially published. Each integration is reverse-engineered and may break when vendors update their portals -- the same fragility tradeoff documented for the existing Tandem cloud integration.

This path is the **third pillar** of how a user can adopt GlycemicGPT, alongside (1) direct device integration via BLE / cloud and (2) third-party platform relays (Nightscout / Loop / AAPS / xDrip+).

### Device Data Support Expansion

- Additional CGM data support (Libre, Medtronic Guardian, Eversense)
- **Linx CGM via Pancares cloud** ([#523](https://github.com/GlycemicGPT/GlycemicGPT/issues/523)) -- Linx is a sub-$50 BLE CGM that uploads to the [Pancares cloud platform](https://equil.pancares.com/login), with strong appeal for users in regions where mainstream CGMs are inaccessible or unaffordable. Community-requested. Integration would require reverse-engineering Pancares' cloud API: the auth flow appears to use a clinician-account-issued QR code (`rppId=...`), and the data path between the Linx mobile app and Pancares is not publicly documented. The project is evaluating priority and engineering effort; if you have insight into Pancares' protocol or can contribute reverse-engineering work, please add to the issue thread.
- Additional **direct pump data reading** drivers via BLE (Omnipod, Medtronic, Dana) -- complementary to the report-ingestion path described in [Pump Report Ingestion](#pump-report-ingestion-adoption-path-for-users-without-direct-integration) above. Direct drivers give live data; report ingestion gives lower-friction adoption.
- Community plugin development examples and tutorials for device data drivers

### AI-Enhanced Endo Reports

- AI analysis integrated into printable reports
- Pattern flags and trend anomalies highlighted for clinician review
- Summary insights designed to facilitate productive endo conversations
- Exportable formats suitable for clinical settings

### Multi-Session Caregiver Escalation

Expand the existing caregiver alerting system into an intelligent, multi-session escalation framework designed for any caregiver relationship -- parents of T1D children, spouses, family members, or anyone the patient trusts with their care.

- **Tiered escalation with context** -- when a patient does not respond to an alert, escalate to their designated caregiver with full context: what triggered the alert, how long it's been active, and relevant pattern history
- **Caregiver feedback loop** -- caregivers can respond to escalated alerts with context that helps refine future analysis (e.g., "had a hard workout this morning" or "stressful day at work today"). All caregiver-provided context is logged transparently to the patient -- nothing the caregiver tells the AI is hidden from the patient.
- **Cross-session AI continuity** -- the AI maintains awareness across sessions so that escalation history, caregiver feedback, and unresolved patterns carry forward rather than resetting each conversation. Persistent memory lives on the user's own infrastructure (self-hosted backend or the user's account on the project's hosted service), consistent with the privacy-first stance: caregiver-provided observations are part of the patient's own data, not a separate analytics surface.
- **Caregiver-initiated queries** -- caregivers can ask the AI questions about the patient's data, trends, and patterns from their own interface without needing access to the patient's full dashboard
- **Collaborative care framing** -- all caregiver features require explicit patient consent and opt-in. The platform frames this as collaborative care, not surveillance. The patient is always aware of and in control of who receives escalated alerts, what information caregivers can access, and what context caregivers have provided to the AI.

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

### Conversational Channel Expansion

The in-app AI chat is and remains the primary conversational surface. Phase 3 explores extending that conversation to additional channels where users prefer to engage -- not as duplicates of the in-app chat, but as legitimate alternative entry points to the same AI.

- **SMS bridge** -- text the AI directly without opening the app. Useful when caregivers prefer text, when the user's phone is locked, or when the conversational rhythm of SMS fits the moment better than a full app session. SMS routes through a third-party gateway (Twilio-class, BAA-required as a PHI processor); the in-app per-message disclaimer is replaced by a one-time onboarding disclaimer plus a footer link in replies, since 160 characters cannot carry the full disclaimer. **The disclaimer model adaptation requires legal review before launch** -- the technical constraint (160 characters) does not automatically compress the legal requirement for informed consent. Launch is gated on counsel sign-off that the onboarding-plus-footer approach meets the same protection standard as the in-app per-message disclaimer.
- **Telegram bot evolution** -- the existing Telegram integration is in alpha and not actively maintained. Phase 3 makes a deliberate polish-or-sunset decision based on whether SMS covers the same use cases more cleanly.
- **Channel-aware AI behavior** -- the AI is aware of which channel it's responding through and adapts message length, formatting, and richness to the channel's constraints (a 160-character SMS reply is not the same as an in-app rich response). Each channel applies an appropriate disclaimer model -- in-app per-message, SMS one-time-plus-footer-link.

**Scope discipline.** Each channel adds an auth surface, a PHI boundary, a maintenance line item, and a medical-disclosure exposure. The project adds channels deliberately, one at a time, with each channel earning its place by demonstrated user demand. All channels are opt-in per user; nothing is enabled by default. Privacy-first applies to each: data flows to and from external platforms only with explicit user consent.

---

## Phase 4 -- Intelligence & Scale

**Focus:** Move from reactive analysis to proactive prediction. Lower the barrier to entry for non-technical users.

### Predictive Analytics

Blood glucose prediction is approached with caution and transparency. Predictions will be built on deterministic mathematical models -- not LLM-based generation. The AI layer may analyze historical data to suggest parameter adjustments for human review, but prediction outputs themselves are rule-based, auditable, and explainable.

- Blood glucose trajectory prediction using insulin-on-board and carb-on-board modeling
- Predictive alerting based on forecasted glucose trends
- Trend forecasting and anomaly detection
- Clear confidence indicators on all predictions

### Advanced Behavioral Analytics

- **Behavioral observation summaries** -- AI surfaces chronic patterns (e.g., glucose excursions concentrated at certain meals, alerts repeatedly dismissed at specific times of day) so the user and their care team can see the long view. The platform surfaces the pattern; medical decisions remain with the user and their care team.
- **Pattern-trend tracking** -- show how identified behavioral patterns evolve over time so the user can see whether things are trending in the direction they want.

### Hosted Service for Non-Technical Users

A managed deployment of GlycemicGPT for users who don't want to run their own infrastructure. Same monitoring-and-analysis platform, hosted by the project under transparent governance and funding.

- Self-hosted remains the primary supported path; the hosted service exists to lower the entry barrier without changing the product
- Identical feature parity with self-hosted (no hosted-only features that fragment the community)
- Transparent pricing, transparent infrastructure costs, and a clear data ownership policy
- AI provider configuration follows the same BYOAI model as self-hosted -- users plug in their own credential (an existing Claude or ChatGPT subscription token, a direct Claude or OpenAI API key, or a local Ollama / OpenAI-compatible endpoint). The hosted service does not act as an AI provider itself.

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

2. **Privacy first.** User health data stays on user-controlled infrastructure. The platform does not phone home, collect telemetry, transmit data to GlycemicGPT or any third party, or use user data to train AI models.

3. **Transparency about AI limitations.** AI makes mistakes. Every AI-generated output is clearly labeled as informational. The platform never presents AI analysis as medical advice. Users are always directed to consult their healthcare team.

4. **Meet users where they are.** Integrations with existing platforms (Nightscout, Loop, AAPS, xDrip) are prioritized over requiring users to switch tools. GlycemicGPT should enhance, not replace.

5. **Open source, always.** The platform is GPL-3.0 licensed. The source code is freely available. Community contributions are welcomed and encouraged. Financial transparency is maintained through Open Collective.

6. **Bug fixes are a perpetual commitment.** Listening to early-adopter feedback and fixing real-world bugs is not a phase that ends. User-reported bugs are prioritized over speculative roadmap work. The bug backlog is public on GitHub Issues. Security and data-loss bugs interrupt phase work for immediate fixing. See [Ongoing -- Community Feedback & Bug Fixes](#ongoing----community-feedback--bug-fixes) for the full posture.

---

## How to Get Involved

| I want to... | Start here |
|--------------|------------|
| Report a bug or request a feature | [Open an issue](https://github.com/GlycemicGPT/GlycemicGPT/issues) |
| Contribute code | [Contributing Guide](CONTRIBUTING.md) |
| Discuss ideas or ask questions | [Community Discord](https://discord.gg/QbyhCQKDBs) |
| Support the project financially | [Open Collective](https://opencollective.com/glycemicgpt) |
| Build a device data plugin | [Contributing Guide](CONTRIBUTING.md#device-data-drivers) (then the [Plugin Architecture Reference](docs/dev/plugin-architecture.md)) |

---

*Because no one should manage diabetes alone.*
