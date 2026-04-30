---
title: Exporting your data
description: Get your CGM, pump, and chat history out of GlycemicGPT in a portable format.
---

GlycemicGPT runs on infrastructure you control, and "self-hosted" doesn't mean much if you can't get your data back out. This page describes what you can export today, how to do it, and what's planned.

> **Honest framing:** GlycemicGPT is alpha software. The export story today is "raw database dump that you can transform into whatever format you need" plus a few in-dashboard CSV exports. AGP-style reports, Tidepool-compatible JSON, and Nightscout-format entries are on the roadmap. If you depend on a specific export format today, **don't make GlycemicGPT your primary data store yet** -- run it alongside Nightscout or Tidepool and let those be the system of record until export parity catches up.

## What you can export today

### Per-table CSV exports from the dashboard

In **Settings → Data → Export**, you can download CSVs for:

- **Glucose readings** (timestamps + values + source)
- **Insulin events** (boluses, basal changes, IoB snapshots)
- **Pump status snapshots** (battery, reservoir, basal rate over time)
- **Alerts** that fired
- **AI chat history** (messages and AI responses)
- **Daily briefs**

You can pick a date range. Exports are point-in-time -- there is no scheduled / recurring export today.

CSVs are not a structured clinical format -- they are simple tables suitable for opening in spreadsheet software, importing into Python / R, or ingesting into your own pipeline. If you need a structured format, see "Roadmap" below.

### Full database dump (for users running Docker)

Everything GlycemicGPT stores lives in a single PostgreSQL database. The most complete export is a `pg_dump`:

```bash
# From the directory where you ran 'docker compose up -d'
docker compose exec db pg_dump -U glycemicgpt glycemicgpt > glycemicgpt-backup.sql
```

That file contains every table -- glucose readings, pump events, AI chat history, user accounts, settings -- in PostgreSQL's standard SQL format. You can restore it on another GlycemicGPT instance, load it into any PostgreSQL database for analysis, or convert it to other formats with `pg_dump`'s flag options (e.g. `-Fc` for compressed binary, `-Fp` for plain SQL, `-Fd` for directory format).

### Full database dump (for users running Kubernetes)

```bash
kubectl exec -n glycemicgpt deploy/postgres -- pg_dump -U glycemicgpt glycemicgpt > glycemicgpt-backup.sql
```

Adjust the namespace and deployment name to match your overlay. The K8s prod overlay also runs a daily `pg_dump` CronJob to a PVC -- see [Install with Kubernetes](../install/kubernetes.md) for the schedule and where the dumps land.

### What the database contains, in plain language

If you want to know what's in there before dumping it -- the platform stores:

- Your account information (email, hashed password, settings)
- Every glucose reading the platform has received from any source
- Every pump event the platform has received (boluses, basal, alarms, settings, IoB samples)
- Every AI chat session (your messages, the AI's responses, model used)
- Every alert that fired and how it was acknowledged
- Every daily brief generated
- Caregiver links and permissions
- AI provider configuration (encrypted; you cannot recover the raw token from a dump because it's stored encrypted with your `SECRET_KEY` and only decrypted in memory)

It does **not** contain anything stored anywhere else (your pump's full memory, anything in your CGM's manufacturer cloud beyond what GlycemicGPT pulled, anything in your AI provider's logs).

## Data formats that are not supported today

If you're coming from another tool and expecting an export here, the honest answer:

- **Tidepool JSON** -- not supported today. Roadmap.
- **Nightscout-format `entries.json` / `treatments.json`** -- not supported today. Roadmap (closely tied to the Phase 2 Nightscout-as-data-source work).
- **AGP (Ambulatory Glucose Profile) PDF** -- not supported today. Roadmap.
- **OpenAPS profile JSON** -- not currently planned. If this matters to you, file an issue.
- **FHIR / HL7** -- not currently planned. Same.

Each of these is a real format with a real audience. They are not in today's release because GlycemicGPT is alpha and prioritized getting basic dashboard / AI / monitoring working before export-format coverage. If one of these is critical for you, file a [feature request](https://github.com/GlycemicGPT/GlycemicGPT/issues/new/choose) -- impact and demand drive the roadmap.

## Importing data into GlycemicGPT

The reverse is also limited today. There is no in-dashboard "import from Nightscout" or "import from Tidepool" button. The Phase 2 Nightscout integration will be a *live* read connection (GlycemicGPT pulls continuously from your Nightscout) rather than a one-time import.

If you have historical CGM data in another tool and want it in GlycemicGPT today, you can:

- Restore a full SQL dump from a previous GlycemicGPT instance (`psql ... < dump.sql`)
- Insert rows directly into the `cgm_readings` and related tables (advanced; you need to know the schema). The schema is in [`apps/api/alembic/versions/`](https://github.com/GlycemicGPT/GlycemicGPT/tree/main/apps/api/alembic/versions).

## Deleting your data

Separate from export -- if you want to wipe your data on the platform:

- **Settings → Account → Delete account** removes your user and cascades to your data
- **Stop the platform and `docker compose down -v`** removes everything including the database volume (irreversible -- only do this after you've taken any backup you want)

See [Privacy](../concepts/privacy.md) for the deletion-vs-retention story.

## "Can I leave?"

Yes. Data is in standard PostgreSQL, exportable with standard tools. The application code is open source. There is no proprietary format or vendor lock that prevents you from taking your data and moving on. The current limitation is that the importable-into-other-tools formats (Tidepool JSON, AGP, etc.) are roadmap items, not shipping today -- so "leaving" today means "you have a SQL dump and you're going to write some translation code to get it into the next tool you use." That's an honest gap, and we expect to close it.
