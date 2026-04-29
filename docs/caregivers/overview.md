---
title: Caregivers Overview
description: How caregiver access works in GlycemicGPT.
---

GlycemicGPT supports a caregiver model for any trusted relationship: parents managing diabetes for a child with type 1, spouses, family members, friends -- anyone the patient explicitly chooses to share access with.

> **Caregiver access is opt-in by the patient, always.** A caregiver cannot be added to your account without your explicit consent. You control what they see and can revoke their access at any time.

## What a caregiver can do

When you link a caregiver to your account, they get their own GlycemicGPT account with limited access to your data:

- **View your dashboard** (read-only) -- they see your glucose, TIR, IoB, recent activity, but cannot change settings or delete data
- **Receive escalated alerts** -- if you don't acknowledge a critical alert (urgent low, sustained high) within a configured time window, the alert escalates to your caregiver
- **Read your daily briefs** (if you've enabled brief sharing)
- **Ask the AI questions about your data** *(coming in ROADMAP §Phase 2 -- not in the platform today)*

What a caregiver **cannot do**:

- Change any of your settings
- Delete or modify any of your data
- See data you haven't explicitly shared with them
- Acknowledge alerts on your behalf (they get notified, but the system still considers the alert un-acknowledged from your end)
- Access your linked devices (Dexcom credentials, Tandem credentials, AI provider keys)

## How caregiver linking works

The flow:

1. **You** (the patient) generate a caregiver invitation in your dashboard
2. The platform produces a one-time invitation code
3. You share the code with your caregiver out-of-band (text, email, in person -- anything secure enough for your situation)
4. **The caregiver** creates a GlycemicGPT account on the same platform you're using and uses the invitation code to link
5. The caregiver's account is now linked to yours, with permissions you set during the invitation

Full step-by-step: [Linking a caregiver to a patient](./linking-to-patient.md).

## Who hosts the caregiver's account?

The caregiver has an account on **your platform** -- the same self-hosted instance you're running. They sign in at the same URL you do (e.g., `https://yourdomain.com`). Their account, their data on the platform, your relationship -- all on infrastructure you control.

This means:

- If you're running locally on your laptop, your caregiver can only sign in when your laptop is online and reachable
- If you're running an always-on deployment (home server with Cloudflare Tunnel, cloud VPS), your caregiver can sign in from anywhere

For caregivers who'd benefit from always-on access (e.g., a parent who needs to see escalated alerts on their phone), an always-on deployment is essentially required.

## Can caregivers manage multiple patients?

Yes. A single caregiver account on a platform can be linked to multiple patient accounts. This is the typical setup for a parent of multiple children with type 1, or a partner who supports two family members.

The caregiver dashboard shows a patient picker; they pick whose data they're looking at right now.

## Can a patient have multiple caregivers?

Yes. You can invite as many caregivers as you want, each with their own permissions. Examples:

- A parent and a school nurse, both with alert-receive permission but only the parent with brief-read permission
- A spouse with full read-only access and an out-of-state grandparent with only urgent-low alert receipt

Each caregiver link is independent -- you can revoke one without affecting the others.

## Privacy and your data

A caregiver linking to your account does not give them access to:

- Your provider credentials (Dexcom Share password, Tandem t:connect credentials, AI provider keys)
- Your `.env` configuration
- Other users' data on the same platform
- Anything outside what's explicitly enabled by their permissions

Caregiver-provided context (e.g., a caregiver responds to an escalated alert with "stressful day at work today") is logged transparently in your data -- nothing the caregiver tells the AI about you is hidden from you. This is a load-bearing principle of the caregiver model: collaborative care, not surveillance.

See [ROADMAP.md](../../ROADMAP.md) §Phase 2 Multi-Session Caregiver Escalation for the planned evolution of caregiver features.

## Revoking a caregiver

In your dashboard, **Settings → Caregivers** lists everyone linked to your account. To revoke:

1. Click the caregiver's entry
2. Click **Revoke access**
3. Confirm

Their account on the platform persists (you don't delete their account; only the link to your data), but they immediately lose access to your dashboard, alerts, and any other shared data. They can be re-invited later if you change your mind.

## Next steps

- **Setting up a caregiver:** [Linking a caregiver to a patient](./linking-to-patient.md)
- **Caregiver-side: receiving alerts:** [Receiving alerts as a caregiver](./receiving-alerts.md)
