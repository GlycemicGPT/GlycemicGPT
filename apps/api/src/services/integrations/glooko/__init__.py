"""Glooko integration (Omnipod Cloud Sync via Glooko, download direction).

Clean-room implementation built from our own live capture of the Glooko web
session + REST API (see ``_bmad-output/planning-artifacts/glooko-reverse-
engineering.md``), NOT derived from the AGPL-3.0 ``nightscout/nightscout-connect``
Glooko driver or ``jpollock/glooko2nightscout-bridge`` -- those are credited as
prior-art protocol references only. Mirrors the Medtronic ``services/integrations/
medtronic/`` modular layout: auth / client / errors / mapper / storage / sync.
"""
