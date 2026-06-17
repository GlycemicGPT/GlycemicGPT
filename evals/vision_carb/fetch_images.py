#!/usr/bin/env python3
"""Fetch licensed eval images from Wikimedia Commons.

Reads dataset/manifest.json, and for every item without a local image, searches
Wikimedia Commons for the item's `search` hint, downloads the top photographic
result (scaled to a vision-friendly size) into dataset/images/, and pins the
resolved `image`, `source_url`, and `license` back into the manifest for
attribution and reproducibility.

Wikimedia Commons content is freely licensed; this keeps the eval set free of
copyright and PHI concerns. Images themselves are gitignored — only the manifest
(ground truth + provenance) is committed.

No third-party dependencies -- standard library only.

Usage:
    python evals/vision_carb/fetch_images.py            # fill any missing images
    python evals/vision_carb/fetch_images.py --force    # re-fetch everything
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

# Item ids become local filenames; constrain them to a safe slug so a crafted
# manifest cannot traverse outside the images directory.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia requires a descriptive, contactable User-Agent.
USER_AGENT = (
    "GlycemicGPT-vision-eval/0.1 (https://github.com/jlengelbrecht/GlycemicGPT)"
)
THUMB_WIDTH = 1024
# Cap downloads so an unexpectedly large response can't exhaust memory.
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
_PHOTO_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _api_get(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def _run_search(query: str) -> list[dict]:
    data = _api_get(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": "6",  # File:
            "gsrlimit": "12",
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": str(THUMB_WIDTH),
        }
    )
    pages = list(data.get("query", {}).get("pages", {}).values())
    pages.sort(key=lambda p: p.get("index", 1_000_000))  # preserve rank order
    return pages


def _photo_from_page(page: dict) -> dict | None:
    info = (page.get("imageinfo") or [{}])[0]
    mime = info.get("mime", "")
    if mime not in _PHOTO_MIME or info.get("width", 0) < 400:
        return None
    thumb = info.get("thumburl") or info.get("url")
    if not thumb:
        return None
    ext = info.get("extmetadata", {})
    return {
        "thumburl": thumb,
        "descriptionurl": info.get("descriptionurl", ""),
        "license": (ext.get("LicenseShortName") or {}).get("value", "unknown"),
        "artist": _strip_html((ext.get("Artist") or {}).get("value", "")),
        "mime": mime,
    }


def _search_image(search: str, category: str | None) -> dict | None:
    """Return the top photo hit, preferring a category-scoped search.

    Full-text Commons search is noisy (it surfaces book scans and unrelated
    files), so we first constrain to the food's category and to bitmaps, then
    progressively relax if that yields nothing.
    """
    candidates = []
    if category:
        candidates.append(f'{search} incategory:"{category}" filetype:bitmap')
    candidates.append(f"{search} filetype:bitmap")
    candidates.append(search)

    for query in candidates:
        for page in _run_search(query):
            photo = _photo_from_page(page)
            if photo:
                return photo
    return None


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value or "").strip()


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        declared = resp.headers.get("Content-Length")
        if declared and int(declared) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"image too large ({declared} bytes)")
        data = resp.read(MAX_DOWNLOAD_BYTES + 1)
        if len(data) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"image exceeds {MAX_DOWNLOAD_BYTES} bytes")
        dest.write_bytes(data)


def _fetch_manifest(manifest_path: Path, force: bool) -> None:
    """Fill any missing images for one manifest and pin provenance back."""
    manifest = json.loads(manifest_path.read_text())
    images_dir = manifest_path.parent / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    print(f"== {manifest_path} ==")
    changed = False
    for item in manifest.get("items", []):
        item_id = item["id"]
        if not _SLUG_RE.match(item_id):
            print(f"  {item_id}: skipped (id is not a safe slug)")
            continue
        existing = item.get("image")
        if existing and (images_dir / existing).exists() and not force:
            print(f"  {item_id}: already present ({existing})")
            continue

        search = item.get("search") or item_id.replace("-", " ")
        category = item.get("category")
        print(f"  {item_id}: searching '{search}' ...", end=" ", flush=True)
        try:
            hit = _search_image(search, category)
        except Exception as exc:  # noqa: BLE001 - best-effort fetch tool
            print(f"SEARCH FAILED ({exc})")
            continue
        if not hit:
            print("NO PHOTO RESULT")
            continue

        ext = _PHOTO_MIME.get(hit["mime"], ".jpg")
        filename = f"{item_id}{ext}"
        try:
            _download(hit["thumburl"], images_dir / filename)
        except Exception as exc:  # noqa: BLE001 - best-effort fetch tool
            print(f"DOWNLOAD FAILED ({exc})")
            continue

        item["image"] = filename
        item["source_url"] = hit["descriptionurl"]
        item["license"] = hit["license"]
        if hit["artist"]:
            item["image_credit"] = hit["artist"]
        else:
            # Don't leave a previous photographer's credit on a replaced image.
            item.pop("image_credit", None)
        changed = True
        print(f"OK -> {filename} [{hit['license']}]")

    if changed:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"  Updated provenance in {manifest_path}")
    else:
        print("  Nothing to update.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).parent
    # Accept one or more manifests so the CLI matches the harness's --manifest.
    parser.add_argument(
        "--manifest",
        nargs="+",
        default=[str(here / "dataset" / "manifest.json")],
        help="one or more manifest paths (default: the v1 easy set)",
    )
    parser.add_argument("--force", action="store_true", help="re-fetch even if present")
    args = parser.parse_args()

    for raw_path in args.manifest:
        _fetch_manifest(Path(raw_path), args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
