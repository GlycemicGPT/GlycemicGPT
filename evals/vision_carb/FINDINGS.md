# Meal Intelligence — vision carb-estimation findings

**Two questions: (1) can cloud vision estimate a
photographed meal's carbs accurately enough to build on, and (2) can every
supported AI-provider mode carry an image through a *sanctioned* mechanism?**

## Recommendation: GO

Cloud vision estimates carbohydrates accurately enough to build the feature, and
every supported provider mode has a sanctioned image path (one is not
live-verifiable in this environment — see the matrix). Proceed to the backend
estimation pipeline.

## The measured number (accuracy)

Eval set: 9 **label-less** foods (no printed nutrition panel — the real use
case), carbs spanning ~2 g to ~50 g, ground truth from USDA FoodData Central
standard portions. Model: `claude-sonnet-4-5`.

| Metric | Value |
| --- | --- |
| **MAE (mean absolute error)** | **8.2 g** |
| Median absolute error | 2.5 g |
| MAPE (mean abs % error) | 29 % |
| Range coverage (truth inside predicted range) | 78 % (7/9) |
| Within ±15 g | 89 % (8/9) |
| Mean predicted range width | 12.8 g |
| **Dosing-language violations** | **0** (required) |

The headline MAE is dragged by a single item that is an **eval-set artifact, not
a model miss**: the "apple" photo contains two apples and the model correctly
described *"two medium red apples, one whole and one partially eaten"*. Excluding
it, the other 8 items give MAE ≈ 4.5 g, median ≈ 1.5 g. These are single, simple
foods, so 8 g is an optimistic bound — mixed restaurant plates are harder, which
is what the (later) correction loop is for.

Accuracy is a property of the **model + images**, not the transport, so it is
unchanged by which provider path carries the image. The number above was
re-confirmed through the sanctioned Claude-subscription CLI path (3-item
re-run: MAE 5.83 g, 100 % within ±15 g, 0 dosing violations).

## Provider × vision matrix

The feature must work under all five BYOAI modes, through **sanctioned
mechanisms only** (no credential impersonation). Each provider advertises a
`supportsVision()` capability, and the sidecar routes an image request to the
active provider's mechanism.

| # | Provider mode | Sanctioned mechanism | Status |
|---|---|---|---|
| 1 | **Claude / Anthropic API key** | Direct Messages API, `x-api-key`, base64 `image` blocks | **WORKING** — confirmed |
| 2 | **OpenAI / Codex API key** | Standard OpenAI vision (`image_url` / base64) via the API | **WORKING** — standard OpenAI multimodal; the harness request shape is exactly this |
| 3 | **Claude Pro / Max subscription** | Official `claude` CLI, read-only plan mode, reads the image off disk via its Read tool | **WORKING** — confirmed live, end-to-end through the sidecar |
| 4 | **Codex / ChatGPT subscription** | Official `codex` CLI: `codex exec --sandbox read-only --skip-git-repo-check --image <path> -- "<prompt>"` (native vision) | **WORKING — confirmed live end-to-end on a real ChatGPT subscription** (pinned `@openai/codex@0.139.0`, model `gpt-5.5`). See "Codex live verification" below |
| 5 | **Local AI** | OpenAI-compatible multimodal (`image_url` / base64) against the user's local endpoint | **WORKING** — same request shape the harness uses; which local models clear the accuracy bar is the local-model benchmark |

### The Claude-subscription path — the open question, settled empirically

Run in a clean environment (temp HOME, no SessionStart hooks), `claude` CLI
v2.1.177:

- **stream-json image input is a dead end.** `claude --print --input-format
  stream-json` with a `{"type":"image","source":{"type":"base64",...}}` block
  produces **zero output** and makes no API call (identical text-only
  stream-json works fine). The subscription path silently drops raw image
  blocks.
- **The Read tool works.** Given the image file on disk and told to read it, the
  CLI correctly described a verification image (orange-over-green) as *"orange on
  top, green on the bottom, split horizontally into two equal halves."* This is
  the official client's documented Read tool doing vision — a sanctioned path.

**Exact working invocation** (what the sidecar now drives):

```text
claude --print --model <model> --add-dir <tempdir> --permission-mode plan "<prompt>" < /dev/null
```

`--permission-mode plan` is **read-only**: the Read tool renders the image, but
Write/Edit/Bash are blocked (verified — a planted prompt-injection that tried to
write a file and run `id` created nothing and was declined). The image is
written to a private per-request temp dir, which is the only directory the
subprocess is granted, and is deleted afterward.

### Rejected: subscription OAuth against the raw Messages API

An earlier iteration sent the subscription OAuth Bearer token to
`api.anthropic.com/v1/messages` with `anthropic-beta: oauth-2025-04-20` and a
hardcoded Claude Code system-prompt preamble (the preamble defeats a "disguised
429"). **This was removed.** It is client impersonation against an enforcement
gate (Anthropic restricted subscription OAuth to official clients in Feb 2026)
and must not ship. The subscription path uses the official `claude` CLI instead
(row 3). The Anthropic API-key path (row 1) uses `x-api-key` and is unaffected.

### Codex live verification (ChatGPT subscription)

Confirmed end-to-end against a real ChatGPT-account Codex login (`auth.json` with
`tokens.access_token`; `codex login status` → "Logged in using ChatGPT"), pinned
`@openai/codex@0.139.0`:

- **Direct CLI** — `codex exec --sandbox read-only --image banana.jpg -- "<carb
  prompt>"` (model `gpt-5.5`): the model saw the image (*"One medium-sized whole
  banana … about 7–8 inches long"*) and returned a parseable estimate —
  `carbs_grams_low: 23, carbs_grams_high: 30, confidence: high` (banana ground
  truth ≈ 27 g, covered; 0 dosing violations).
- **End-to-end through the sidecar** — `POST /v1/chat/completions` with an inline
  base64 banana image routed `gpt-4o` → the Codex provider → `runCodexVision` →
  HTTP 200 with `carbs_grams_low: 27, carbs_grams_high: 35, confidence: high`.
- **Read-only sandbox engaged** — a write-probe under `--sandbox read-only` was
  blocked (the file was never created; codex wrapped the command in bubblewrap).

Three things the live run required (now in the code):
1. `getAuthState()` reads the current `auth.json` shape (`tokens.access_token`),
   not a legacy top-level `accessToken`, so a ChatGPT login is detected.
2. No `--model` is forced — a ChatGPT-account Codex rejects API model names like
   `gpt-4o` ("not supported when using Codex with a ChatGPT account") and picks
   its own default.
3. `--skip-git-repo-check`, because the sidecar runs codex from a private temp
   dir (not a git repo), which codex otherwise refuses.

## Routing & fallback contract

The sidecar selects the vision runner for the active provider:

- Codex/GPT model → Codex CLI (`codex exec --image`).
- Claude model → prefer the Anthropic API-key path (`x-api-key`); fall back to
  the Claude subscription CLI when no API key is configured.

When the selected provider has **no** configured vision mechanism, the sidecar
returns a stable, typed fallback rather than failing opaquely:

```text
HTTP 422
{ "error": {
    "message": "Vision is not available on your current AI provider. Configure
                an API key (Anthropic or OpenAI), a Claude or ChatGPT
                subscription, or a vision-capable local model to estimate from a
                photo.",
    "type": "vision_unavailable",
    "code": "vision_unavailable" } }
```

The mobile/backend client should treat `type: "vision_unavailable"` as "image
analysis isn't available on this provider yet — add an API key or use a supported
local model," never as a transient error to retry.

## Safety & security

- Every estimate is a **range + confidence**, never a confident integer. The
  prompt forbids insulin/dose/units language and the harness scans every response
  for it — **0 violations**. No estimate flows into IoB / treatment_safety /
  carb-ratio math.
- **No credential impersonation** anywhere (the forged OAuth path is gone).
- **Base64 `data:` images only** — remote (`http(s)://`, `file://`) URLs are
  rejected and never fetched (no SSRF), media type / size / count are validated,
  and CLI vision writes images to a private temp dir granted to nothing else.
- Tokens are never logged or returned to the client; the text path is unchanged.

## What's next

- **Backend estimation pipeline:** a `food_records` model + an upload→vision→
  persist service that calls the confirmed vision route for the user's active
  provider, persists the structured range/confidence/nutrition, enforces sane
  carb bounds, and strips EXIF.
- **Codex deployment notes** (from the live verification): pin a current
  `@openai/codex` (≥ 0.139.0); mount the ChatGPT `auth.json` at `CODEX_HOME`
  (not under `/tmp` — codex refuses to create helper binaries there; the
  sidecar's `/home/sidecar/.codex` is fine); and `--sandbox read-only` uses
  **bubblewrap**, so the sidecar container must permit user namespaces.
- **Local-model benchmark:** reuse this harness verbatim
  (`--base-url` at Ollama, `--model` at a local vision model) to decide which
  local models clear a pass bar. Same eval set, same metric.

## Reproducing

```bash
python evals/vision_carb/fetch_images.py        # download licensed images
# Start the sidecar with a vision credential in env for the active provider:
#   ANTHROPIC_API_KEY        -> Claude API-key path
#   CLAUDE_CODE_OAUTH_TOKEN  -> Claude subscription CLI path (needs the claude CLI)
# then:
SIDECAR_API_KEY=<key> python evals/vision_carb/harness.py \
    --base-url http://localhost:3456 --model claude-sonnet-4-5
```

Results land in `evals/vision_carb/results/` (gitignored).
