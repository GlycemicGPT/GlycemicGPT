---
title: Linking a Caregiver to a Patient
description: Step-by-step setup for inviting and accepting a caregiver invitation.
---

This page covers the full caregiver linking flow -- generating the invitation as the patient, accepting it as the caregiver, and configuring permissions.

If you're new to the caregiver model, read the [Caregivers Overview](./overview.md) first.

> **Known gaps -- being addressed in [issue #521](https://github.com/GlycemicGPT/GlycemicGPT/issues/521):**
>
> - **Email-based invitations are not yet supported.** The platform doesn't have SMTP configured today, so invitation codes are shared manually. Cloud / public deployments will eventually want SMTP for a polished invite-by-email flow.
> - **Self-signup is always enabled.** There's no admin setting today to disable the public signup endpoint, which means anyone who reaches your platform's URL can create an account. **For cloud / public deployments, this is a security concern** until the disable-signup setting lands. For now: only run a publicly-reachable deployment with people you trust on your network, or accept the risk consciously.
>
> Both are tracked in [issue #521](https://github.com/GlycemicGPT/GlycemicGPT/issues/521). The workarounds described on this page are the official offline / no-SMTP path until those land.

> **Both the patient and the caregiver use the same GlycemicGPT platform.** The caregiver is a regular GlycemicGPT user account on your platform; what makes them a caregiver is the link between their account and yours. They sign in at the same URL you do.

## If the patient is a child or a dependent you manage

The most common caregiver scenario is a parent (or other primary caregiver) running GlycemicGPT for a child with type 1 diabetes. The page below describes a flow with two separate adults each with their own account, but if the patient is a minor or someone whose care you manage, **you'll typically hold both accounts yourself**:

- The **patient account** is the one whose dashboard shows the child's data. Set this up first using the child's name (or whatever label you prefer). This account "owns" the data on the platform.
- The **caregiver account** is yours -- a separate account that's linked to the patient account. This is the one you sign in to day-to-day; it's also the one that receives escalated alerts and can be granted to other family members later (other parent, grandparent, school nurse).

The flow:

1. Sign up for the platform once with the patient details. Get the dashboard working, pump connected, AI configured. (This is the [Get Started](../get-started.md) guide.)
2. From that account, go to **Settings → Caregivers** and follow the **Patient side** steps below to generate an invitation for yourself.
3. Sign out, sign back up as a new account using your own email. (You can also use a different browser or an incognito window to avoid signing out repeatedly.)
4. Follow the **Caregiver side** steps below to accept the invitation under your new account.

You now have two accounts on your platform: the patient account (rarely used directly) and your caregiver account (used daily). To add another family member as an additional caregiver, sign back in to the patient account and generate a new invitation for them. You can have as many caregivers as you want.

This same pattern works for any "I'm running this on behalf of someone else" situation: an adult child managing a parent's diabetes, a spouse managing the other spouse's data, etc.

## Patient side: generating an invitation

These steps are done by the patient in their own dashboard.

### 1. Go to caregiver settings

In the dashboard, **Settings → Caregivers**.

If this is your first caregiver, you'll see an empty list with a **Invite caregiver** button. If you already have caregivers, the existing list shows here.

### 2. Click "Invite caregiver"

A form appears. Fill in:

- **Caregiver's name (or label)** -- so you remember who this invitation is for. Examples: "Mom," "Dr. Smith's nurse," "school nurse."
- **Their email** -- the address they'll use to sign in to GlycemicGPT
- **Permissions** -- pick what they can see and do:
  - **View dashboard** (read-only)
  - **Receive escalated alerts** -- they get alert notifications when you don't acknowledge urgent alerts in time
  - **Read daily briefs**
  - **Ask AI questions about my data** *(coming in a future release; reserved checkbox today)*
- **Escalation window** (only applies if alert escalation is on) -- how long after an unacknowledged alert before it escalates to this caregiver. Default 15 minutes.

### 3. Generate the invitation code

Click **Generate invitation**. The platform creates a one-time-use code -- a long random string. The code is valid for 7 days; if the caregiver doesn't accept it in that window, you'll need to generate a new one.

### 4. Share the code

Send the invitation code to your caregiver via whatever channel you trust:

- Text message
- Email
- In person
- A secure messaging app

The code by itself doesn't grant access -- it has to be paired with the caregiver creating an account on your platform.

> **Treat the invitation code like a temporary password.** Anyone who has both the code AND your platform's URL can create a caregiver account linked to you. Don't post it publicly.

### 5. Wait for the caregiver to accept

You'll see the invitation status in **Settings → Caregivers**:

- **Pending** -- the code has been generated but not yet used
- **Active** -- the caregiver has registered and the link is live
- **Expired** -- 7 days passed without use

You can revoke a pending invitation at any time -- click it and choose **Cancel invitation**.

## Caregiver side: accepting the invitation

These steps are done by the caregiver, with the invitation code in hand.

### 1. Navigate to the platform's URL

The patient should have shared this with you along with the invitation code -- something like `https://glycemicgpt.example.com`.

### 2. Sign up for an account

If this is your first time using GlycemicGPT for this patient, click **Sign up** and create a new account with your email and a password.

If you already have an account on this platform (because you're already a caregiver for someone else, or you also use the platform yourself), sign in with your existing credentials.

### 3. Accept the invitation

Once signed in, go to **Settings → Caregiver Links → Accept invitation**.

Paste the invitation code the patient gave you. The platform validates it and creates the link.

### 4. You're now a caregiver

Your dashboard shows the patient(s) you have access to. If you're a caregiver for multiple patients, a patient picker lets you switch between them.

If you only have caregiver access to one patient, the dashboard goes straight to their data.

## After linking: ongoing management

### Patient: changing permissions

You can change a caregiver's permissions at any time without re-inviting them. **Settings → Caregivers → click the caregiver → edit permissions**.

### Patient: revoking access

**Settings → Caregivers → click the caregiver → Revoke access**. The caregiver immediately loses visibility into your data; their account on the platform is preserved (in case they're a caregiver for other patients on the same platform) but the link to you is severed.

### Caregiver: removing yourself

**Settings → Caregiver Links → unlink from this patient**. Same effect as the patient revoking you, but initiated from your side.

## Common issues

### "Invalid invitation code"

- You may have copied the code with extra whitespace -- try again
- The code may have expired (7-day limit) -- ask the patient for a new one
- The patient may have revoked the invitation before you used it

### "User already exists"

You're trying to register with an email that's already on this platform. Sign in instead, then accept the invitation under your existing account.

### "Cannot reach the platform"

Same root cause as any "dashboard won't load" -- see the patient's [Troubleshooting](../troubleshooting/dashboard-wont-load.md). For a caregiver, the most common case is the patient's platform isn't running 24/7 (e.g., it's on a laptop that's currently asleep), or it's only reachable on the patient's home network.

### Caregiver wants to see live data when away from the patient's home network

The patient's platform must be reachable from the internet. Either:

- The patient runs a [Cloudflare Tunnel deployment](../install/docker.md#deploying-with-cloudflare-tunnel-home-server-or-vps) (home server or VPS) -- caregiver works from anywhere
- The patient runs a [VPS with Caddy + Let's Encrypt](../install/docker.md#deploying-to-a-vps-with-https) -- caregiver works from anywhere
- The patient runs only locally on their laptop -- caregiver can only see data when on the same Wi-Fi as the patient's laptop

For most caregiver use cases, an always-on deployment is essentially required.

## What happens to the caregiver account if I delete my GlycemicGPT account?

The caregiver's link to you is severed (they lose access to your data). Their account on the platform persists -- if they're a caregiver for other patients on the same platform, their other links remain intact.
