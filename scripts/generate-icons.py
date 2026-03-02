#!/usr/bin/env python3
"""
Generate all app icon assets from the source logo.

Produces:
  - Android adaptive icon foreground PNGs (main, debug w/ DEV badge, wear)
  - Android legacy launcher + round PNGs at all densities
  - Android monochrome icon PNGs for themed icons (Android 13+)
  - Web favicons (ICO, PNG 16/32, SVG), apple-touch-icon, PWA icons
  - Maskable PWA icon with solid background and safe zone
  - Play Store high-res icon (512px)

Usage:
    python3 scripts/generate-icons.py

Requires: Pillow (pip install Pillow)
"""

import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Resolve project root (parent of scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGO_PATH = PROJECT_ROOT / "assets" / "logo.png"
ICON_ONLY_DIR = PROJECT_ROOT / "assets" / "icon-only"

PHONE_MAIN_RES = PROJECT_ROOT / "apps" / "mobile" / "app" / "src" / "main" / "res"
PHONE_DEBUG_RES = PROJECT_ROOT / "apps" / "mobile" / "app" / "src" / "debug" / "res"
WEAR_MAIN_RES = PROJECT_ROOT / "apps" / "mobile" / "wear" / "src" / "main" / "res"
WEB_PUBLIC = PROJECT_ROOT / "apps" / "web" / "public"

BG_COLOR = (15, 23, 42, 255)  # #0F172A navy

# Android density -> adaptive foreground size (108dp * factor)
ANDROID_DENSITIES = {
    "mdpi": 108,
    "hdpi": 162,
    "xhdpi": 216,
    "xxhdpi": 324,
    "xxxhdpi": 432,
}


def load_icon_only(logo_path: Path) -> Image.Image:
    """Crop the water drop icon from the full logo (removes text)."""
    img = Image.open(logo_path).convert("RGBA")
    pixels = img.load()
    width, height = img.size

    # Find the gap between icon and text by scanning for empty rows
    row_counts = []
    for y in range(height):
        count = sum(1 for x in range(width) if pixels[x, y][3] > 10)
        row_counts.append(count)

    # Find gap between icon and text: scan from top, find a sustained run of
    # near-empty rows after content starts. Tolerant threshold (<=5 opaque pixels)
    # handles anti-aliased edges that aren't perfectly empty.
    icon_bottom = 0
    in_content = False
    gap_run = 0
    for y in range(height):
        if row_counts[y] > 5:
            in_content = True
            icon_bottom = y
            gap_run = 0
        elif in_content and row_counts[y] <= 5:
            gap_run += 1
            if gap_run >= 3:
                # Found sustained gap - icon ends at icon_bottom
                break

    # Find horizontal bounds for icon portion
    min_x, max_x = width, 0
    try:
        first_row = next(y for y in range(height) if row_counts[y] > 5)
    except StopIteration:
        raise ValueError(
            f"No opaque icon content found in {logo_path}. "
            "Expected a logo image with visible pixels."
        )
    for y in range(first_row, icon_bottom + 1):
        for x in range(width):
            if pixels[x, y][3] > 10:
                min_x = min(min_x, x)
                max_x = max(max_x, x)

    # Crop with small padding
    pad = 20
    crop = img.crop((
        max(0, min_x - pad),
        max(0, first_row - pad),
        min(width, max_x + pad),
        min(height, icon_bottom + pad),
    ))

    # Make square and resize to 1024
    w, h = crop.size
    size = max(w, h)
    square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    square.paste(crop, ((size - w) // 2, (size - h) // 2))
    return square.resize((1024, 1024), Image.LANCZOS)


def make_adaptive_foreground(icon: Image.Image, size: int) -> Image.Image:
    """Place icon within adaptive icon safe zone (66/108 of canvas)."""
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    safe_size = int(size * 66 / 108)
    inner_size = int(safe_size * 0.92)
    scaled = icon.resize((inner_size, inner_size), Image.LANCZOS)
    offset = (size - inner_size) // 2
    canvas.paste(scaled, (offset, offset), scaled)
    return canvas


def make_monochrome(icon: Image.Image, size: int) -> Image.Image:
    """Create a monochrome silhouette for Android 13 themed icons."""
    fg = make_adaptive_foreground(icon, size)
    # Convert to grayscale silhouette: any opaque pixel becomes white
    mono = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fg_pixels = fg.load()
    mono_pixels = mono.load()
    for y in range(size):
        for x in range(size):
            a = fg_pixels[x, y][3]
            if a > 30:
                mono_pixels[x, y] = (255, 255, 255, a)
    return mono


def add_dev_badge(img: Image.Image) -> Image.Image:
    """Add a red 'DEV' badge. Uses minimum pixel size floor for legibility."""
    img = img.copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size

    # Badge dimensions -- enforce minimum sizes for legibility
    badge_w = max(int(w * 0.38), 22)
    badge_h = max(int(h * 0.16), 10)

    badge_x = w - badge_w - max(int(w * 0.12), 2)
    badge_y = h - badge_h - max(int(h * 0.14), 2)

    corner_r = max(int(badge_h * 0.3), 2)
    outline_w = max(1, int(w * 0.005))

    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=corner_r,
        fill=(220, 38, 38, 230),
        outline=(255, 255, 255, 200),
        width=outline_w,
    )

    # Font size with minimum floor of 7px for readability
    font_size = max(int(badge_h * 0.65), 7)
    font = _load_font(font_size)

    text = "DEV"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = badge_x + (badge_w - text_w) // 2
    text_y = badge_y + (badge_h - text_h) // 2 - max(int(badge_h * 0.08), 1)

    draw.text((text_x, text_y), text, fill=(255, 255, 255, 255), font=font)
    return img


FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "DejaVuSans-Bold.ttf"


def _load_font(size: int):
    """Load the repository-pinned font for deterministic badge rendering."""
    if not FONT_PATH.exists():
        raise FileNotFoundError(
            f"Missing pinned font at {FONT_PATH}. "
            "Add DejaVuSans-Bold.ttf to assets/fonts/ for reproducible icon generation."
        )
    return ImageFont.truetype(str(FONT_PATH), size)


def make_legacy_launcher(icon: Image.Image, size: int, with_bg: bool = True) -> Image.Image:
    """Create a legacy square launcher icon."""
    canvas = Image.new("RGBA", (size, size), BG_COLOR if with_bg else (0, 0, 0, 0))
    inner = int(size * 0.75)
    scaled = icon.resize((inner, inner), Image.LANCZOS)
    offset = (size - inner) // 2
    canvas.paste(scaled, (offset, offset), scaled)
    return canvas


def make_round_launcher(icon: Image.Image, size: int) -> Image.Image:
    """Create a legacy round launcher icon with circular mask."""
    square = make_legacy_launcher(icon, size, with_bg=True)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(square, (0, 0), mask)
    return result


def optimize_png(img: Image.Image) -> Image.Image:
    """Pass-through for future PNG optimization (quantization, metadata stripping).

    Currently a no-op -- Pillow's save(..., optimize=True) in save_png()
    handles basic compression. Full palette quantization deferred until
    icon file sizes become a concern.
    """
    return img


def save_png(img: Image.Image, path: Path):
    """Save PNG with optimization."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = optimize_png(img)
    img.save(str(path), optimize=True)


def generate_android_icons(icon: Image.Image, res_dir: Path, debug: bool = False):
    """Generate all Android icon PNGs for a resource directory."""
    for density, fg_size in ANDROID_DENSITIES.items():
        mipmap_dir = res_dir / f"mipmap-{density}"

        # Adaptive foreground
        fg = make_adaptive_foreground(icon, fg_size)
        if debug:
            fg = add_dev_badge(fg)
        save_png(fg, mipmap_dir / "ic_launcher_foreground.png")

        # Monochrome (themed icon, Android 13+)
        mono = make_monochrome(icon, fg_size)
        if debug:
            mono = add_dev_badge(mono)
        save_png(mono, mipmap_dir / "ic_launcher_monochrome.png")

        # Legacy launcher icons (48dp * density factor)
        launcher_size = int(fg_size * 48 / 108)
        launcher = make_legacy_launcher(icon, launcher_size)
        if debug:
            launcher = add_dev_badge(launcher)
        save_png(launcher, mipmap_dir / "ic_launcher.png")

        round_icon = make_round_launcher(icon, launcher_size)
        if debug:
            round_icon = add_dev_badge(round_icon)
        save_png(round_icon, mipmap_dir / "ic_launcher_round.png")

        print(f"  {mipmap_dir.relative_to(PROJECT_ROOT)}/ ({fg_size}px fg, {launcher_size}px legacy)")


def generate_web_icons(icon: Image.Image):
    """Generate web favicons, apple-touch-icon, PWA icons."""
    # Favicons (transparent bg)
    for size, name in [(16, "favicon-16x16.png"), (32, "favicon-32x32.png")]:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        inner = int(size * 0.9)
        scaled = icon.resize((inner, inner), Image.LANCZOS)
        offset = (size - inner) // 2
        canvas.paste(scaled, (offset, offset), scaled)
        save_png(canvas, WEB_PUBLIC / name)
        print(f"  {name} ({size}px)")

    # Multi-size ICO (16, 32, 48, 64)
    ico_sizes = [16, 32, 48, 64]
    ico_images = []
    for s in ico_sizes:
        canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        inner = int(s * 0.9)
        scaled = icon.resize((inner, inner), Image.LANCZOS)
        offset = (s - inner) // 2
        canvas.paste(scaled, (offset, offset), scaled)
        ico_images.append(canvas)
    ico_images[0].save(
        str(WEB_PUBLIC / "favicon.ico"),
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=ico_images[1:],
    )
    print(f"  favicon.ico (multi-size: {ico_sizes})")

    # Apple touch icon (solid bg, 180px)
    apple = Image.new("RGBA", (180, 180), BG_COLOR)
    inner = int(180 * 0.78)
    scaled = icon.resize((inner, inner), Image.LANCZOS)
    offset = (180 - inner) // 2
    apple.paste(scaled, (offset, offset), scaled)
    save_png(apple, WEB_PUBLIC / "apple-touch-icon.png")
    print("  apple-touch-icon.png (180px)")

    # PWA icon (transparent, 192px)
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png")]:
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        inner = int(size * 0.85)
        scaled = icon.resize((inner, inner), Image.LANCZOS)
        offset = (size - inner) // 2
        canvas.paste(scaled, (offset, offset), scaled)
        save_png(canvas, WEB_PUBLIC / name)
        print(f"  {name} ({size}px)")

    # Maskable PWA icon (solid bg, 10% safe zone padding, 512px)
    maskable = Image.new("RGBA", (512, 512), BG_COLOR)
    # Maskable safe zone: content within inner 80% (10% padding each side)
    safe_inner = int(512 * 0.72)  # 80% of 90% for breathing room
    scaled = icon.resize((safe_inner, safe_inner), Image.LANCZOS)
    offset = (512 - safe_inner) // 2
    maskable.paste(scaled, (offset, offset), scaled)
    save_png(maskable, WEB_PUBLIC / "icon-maskable-512.png")
    print("  icon-maskable-512.png (512px, maskable)")

    # SVG favicon (simple wrapper embedding the PNG as data URI)
    # For a true vector SVG we'd need the original vector source; this is a pragmatic fallback
    import base64
    from io import BytesIO

    svg_icon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    inner = int(64 * 0.9)
    scaled = icon.resize((inner, inner), Image.LANCZOS)
    offset = (64 - inner) // 2
    svg_icon.paste(scaled, (offset, offset), scaled)
    buf = BytesIO()
    svg_icon.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()

    svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <image href="data:image/png;base64,{b64}" width="64" height="64"/>
</svg>
'''
    (WEB_PUBLIC / "favicon.svg").write_text(svg_content)
    print("  favicon.svg")


def generate_source_assets(icon: Image.Image):
    """Generate source/reference assets."""
    ICON_ONLY_DIR.mkdir(parents=True, exist_ok=True)
    save_png(icon, ICON_ONLY_DIR / "icon-1024.png")
    print("  icon-1024.png (1024px source)")

    # Play Store icon (512px, solid bg)
    store = Image.new("RGBA", (512, 512), BG_COLOR)
    inner = int(512 * 0.78)
    scaled = icon.resize((inner, inner), Image.LANCZOS)
    offset = (512 - inner) // 2
    store.paste(scaled, (offset, offset), scaled)
    save_png(store, ICON_ONLY_DIR / "play-store-512.png")
    print("  play-store-512.png (512px)")


def main():
    if not LOGO_PATH.exists():
        print(f"ERROR: Logo not found at {LOGO_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading logo from {LOGO_PATH}...")
    icon = load_icon_only(LOGO_PATH)

    print("\n--- Source assets ---")
    generate_source_assets(icon)

    print("\n--- Phone main icons ---")
    generate_android_icons(icon, PHONE_MAIN_RES, debug=False)

    print("\n--- Phone debug icons (DEV badge) ---")
    generate_android_icons(icon, PHONE_DEBUG_RES, debug=True)

    print("\n--- Wear OS icons ---")
    generate_android_icons(icon, WEAR_MAIN_RES, debug=False)

    print("\n--- Web icons ---")
    generate_web_icons(icon)

    print("\nAll icon assets generated successfully!")


if __name__ == "__main__":
    main()
