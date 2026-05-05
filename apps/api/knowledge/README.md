# Bootstrap knowledge directory

`seed_knowledge_base()` reads markdown files from this directory at API
startup and stores them in `knowledge_chunks` with
`trust_tier='AUTHORITATIVE'`. AUTHORITATIVE is the privileged tier:
chunks tagged this way bypass the runtime prompt-injection filter in
`src/services/knowledge_retrieval.py`.

## What is allowed here (the rule)

Only ecosystem and technical reference material:

- Architecture, API, and integration documentation for OSS diabetes
  platforms (Loop, AAPS, Trio, OpenAPS, xDrip+, Nightscout, Nocturne)
- Mappings between platforms (e.g., how the same concept is named in
  Loop vs. AAPS)
- Vendor-published *technical specs* that are pure facts about a
  device (sensor lifetime, communication protocols, file formats) and
  not framed as advice or thresholds
- GlycemicGPT-specific architectural notes that ground the AI in how
  this codebase is organized

## What is NOT allowed here

**No clinical content.** Specifically excluded:

- Glycemic target ranges (TIR, A1C goals, hypoglycemia thresholds)
- Drug data that drives dosing decisions (insulin onset/peak/duration
  curves, medication interactions, dosage calculations)
- Treatment guidance (15-15 rule, when to escalate, sick-day
  protocols, exercise adjustments)
- Anything that reads as "what your target should be," "what dose to
  take," or "how to manage condition X"

The reasoning: GlycemicGPT is not a medical authority. Clinical content
shipped here would influence the AI's responses about a user's health
data the AI is already reading, transferring liability for clinical
accuracy onto the project. That's the wrong place for it.

## Where clinical content lives instead

Clinical content reaches the AI through user-controlled paths:

- **`USER_PROVIDED` tier** — documents the user uploads via the
  dashboard knowledge-base UI. Per-user scope.
- **`RESEARCHED` tier** — content the AI fetched from URLs the user
  configured as `ResearchSource` rows. The user picks which sources
  the AI is allowed to read from. Runs through the runtime
  injection filter.
- **`EXTRACTED` tier** — facts the AI noticed in the user's chat
  history. Per-user scope.

A future feature (Epic 45 internally) will let the AI propose new
RESEARCHED additions based on the user's settings (pump, CGM, insulin
type, configured TIR range), validate them against trusted sources, and
surface a request for the user's explicit approval before adding
anything to RAG. The project never auto-adds clinical content; the user
always decides.

## Threat model for AUTHORITATIVE content

Even within the "ecosystem only" rule, AUTHORITATIVE bypasses the
runtime injection filter, so anything in this directory is effectively
system-prompt-equivalent content with respect to AI chat. Treat each
new file as a system-prompt change.

`seed_knowledge_base()` runs every chunk through a small set of
injection-pattern regexes at ingest time (mirror of the runtime
filter). If any chunk matches, the **entire file** is rejected and the
seed continues with the remaining files. The rejection is logged at
`WARNING` level with the file name.

**The regex check is defense-in-depth, not a guarantee.** Sophisticated
prompt injection (paraphrasing, multilingual phrasing, encoded
payloads) bypasses simple pattern matching trivially. Every file in
this directory **must** undergo human review by a maintainer who has
read this README. The CODEOWNERS rule on `apps/api/knowledge/**`
enforces that review at the GitHub level. Do not treat a green seed
log as evidence that content is safe.

Examples of patterns that currently block ingestion (the authoritative
list lives in `_INJECTION_PATTERNS` in
`apps/api/src/services/knowledge_seed.py` and may grow over time):

- `ignore (all )?previous instructions`
- `you are now`
- `system prompt:`
- `override (safety|guidelines|protocol)`
- `do not mention this`

If a legitimate technical passage trips a pattern (rare but possible --
e.g. a paper title quoting the prompt-injection literature), rephrase
the passage rather than weakening the regex set.

## Adding new files

1. Confirm the content fits the "what is allowed" rule above. If it's
   clinical, this is the wrong place — clinical content belongs in
   the user-controlled tiers.
2. Add a new `.md` file in this directory with an `# H1` title.
3. Per-chunk `content_hash` dedup means re-running the seed is
   idempotent. Adding a new file picks it up automatically on next
   API restart.
4. The Dockerfile copies the entire directory into the image, so new
   files ship with the next container build.

## Files excluded from ingestion

The seed automatically skips:

- `README.md` (this file -- documents injection patterns it would
  otherwise reject)
- `.gitkeep` (placeholder so the empty directory ships in git)
- Any file starting with `_` (e.g., `_draft-foo.md` for in-progress
  drafts)

## Review requirements

`apps/api/knowledge/**` is owned by the maintainer team via CODEOWNERS
(see `.github/CODEOWNERS`). Changes here require maintainer review even
if the rest of the PR does not.
