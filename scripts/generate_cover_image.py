#!/usr/bin/env python3
"""Generate a terminal-style banner for Codex SEO."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


WIDTH = 1792
HEIGHT = 598

NEON = (96, 255, 178, 255)
NEON_SOFT = (124, 255, 206, 255)
TEXT = (212, 255, 232, 255)
PANEL = (3, 10, 16, 205)
BORDER = (58, 190, 136, 200)


def load_font(size: int, *, mono: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fonts: list[str] = []
    if mono:
        if bold:
            fonts.extend(
                [
                    "C:/Windows/Fonts/lucon.ttf",
                    "C:/Windows/Fonts/CascadiaMono.ttf",
                    "C:/Windows/Fonts/CascadiaCode.ttf",
                    "C:/Windows/Fonts/consolab.ttf",
                    "C:/Windows/Fonts/courbd.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
                ]
            )
        fonts.extend(
            [
                "C:/Windows/Fonts/lucon.ttf",
                "C:/Windows/Fonts/CascadiaMono.ttf",
                "C:/Windows/Fonts/CascadiaCode.ttf",
                "C:/Windows/Fonts/consola.ttf",
                "C:/Windows/Fonts/cour.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            ]
        )
    else:
        if bold:
            fonts.extend(
                [
                    "C:/Windows/Fonts/segoeuib.ttf",
                    "C:/Windows/Fonts/arialbd.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                ]
            )
        fonts.extend(
            [
                "C:/Windows/Fonts/segoeui.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )

    for f in fonts:
        try:
            return ImageFont.truetype(f, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def fit_text(draw: ImageDraw.ImageDraw, text: str, max_w: int, *, mono: bool = True, bold: bool = False, start_size: int = 32) -> tuple[str, ImageFont.ImageFont]:
    for size in range(start_size, 11, -1):
        font = load_font(size, mono=mono, bold=bold)
        if text_width(draw, text, font) <= max_w:
            return text, font
    # Hard clamp with ellipsis if needed
    font = load_font(12, mono=mono, bold=bold)
    t = text
    while t and text_width(draw, t + "...", font) > max_w:
        t = t[:-1]
    return (t + "..." if t else "..."), font


def clamp_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int) -> str:
    if text_width(draw, text, font) <= max_w:
        return text
    t = text
    while t and text_width(draw, t + "...", font) > max_w:
        t = t[:-1]
    return (t + "...") if t else "..."


def make_background() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), (2, 8, 14))
    px = img.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            fx = x / WIDTH
            fy = y / HEIGHT
            r = int(2 + 8 * fx)
            g = int(8 + 28 * fx + 10 * (1 - fy))
            b = int(12 + 18 * fy + 8 * (1 - fx))
            px[x, y] = (r, g, b)
    return img.convert("RGBA")


def add_scanlines(img: Image.Image) -> None:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(0, HEIGHT, 3):
        d.line((0, y, WIDTH, y), fill=(0, 0, 0, 24), width=1)
    img.alpha_composite(overlay)


def add_glow(img: Image.Image, center: tuple[int, int], radius: int, color: tuple[int, int, int, int]) -> None:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    cx, cy = center
    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius // 2))
    img.alpha_composite(overlay)


def draw_banner() -> Image.Image:
    bg = make_background()
    add_glow(bg, (360, 160), 280, (20, 160, 120, 80))
    add_glow(bg, (1360, 180), 240, (24, 120, 96, 75))
    add_glow(bg, (1320, 510), 240, (10, 92, 70, 60))
    add_scanlines(bg)

    d = ImageDraw.Draw(bg)

    left = (52, 36, 920, 560)
    right = (968, 36, 1738, 560)

    d.rounded_rectangle(left, radius=30, fill=PANEL, outline=BORDER, width=2)
    d.rounded_rectangle(right, radius=30, fill=PANEL, outline=BORDER, width=2)

    title_font = load_font(140, mono=True, bold=True)
    sub_title_font = load_font(132, mono=True, bold=True)
    meta_font = load_font(58, mono=True, bold=True)
    right_title = load_font(52, mono=True, bold=True)

    # Left panel title
    for dx, dy, color in [(-2, -2, (0, 22, 12, 230)), (2, 2, (0, 22, 12, 230)), (0, 0, NEON)]:
        d.text((92 + dx, 54 + dy), "CODEX", font=title_font, fill=color)
    for dx, dy, color in [(-2, -2, (0, 22, 12, 230)), (2, 2, (0, 22, 12, 230)), (0, 0, NEON_SOFT)]:
        d.text((92 + dx, 195 + dy), "SEO", font=sub_title_font, fill=color)

    d.line((88, 372, 864, 372), fill=(78, 233, 173, 255), width=6)
    d.text((88, 406), "AI-POWERED SEO ANALYSIS", font=meta_font, fill=TEXT)

    # Right panel, intent style (not slash-command style)
    d.text((1000, 62), "[PROMPT INTENTS]", font=right_title, fill=(164, 255, 217, 255))
    d.line((1000, 126, 1710, 126), fill=(83, 230, 169, 255), width=4)

    lines = [
        "$ full seo audit for <url>",
        "$ deep page analysis for <url>",
        "$ technical seo review for <url>",
        "$ content quality + eeat for <url>",
        "$ schema analyze or generate",
        "$ sitemap analyze or generate",
        "$ geo / ai citation check",
        "$ hreflang validate or generate",
        "$ programmatic analyze or plan",
        "$ competitor page strategy + plan",
    ]

    max_line_width = right[2] - right[0] - 64
    line_font = load_font(22, mono=True, bold=False)
    y = 152
    for line in lines:
        safe_line = clamp_text(d, line, line_font, max_line_width)
        d.text((1002, y), safe_line, font=line_font, fill=(194, 255, 229, 242))
        y += 33

    footer_text, footer_font = fit_text(
        d,
        "codex-seo // deterministic runners + skill orchestration",
        max_line_width,
        mono=True,
        bold=False,
        start_size=26,
    )
    d.text((1002, 522), footer_text, font=footer_font, fill=(126, 233, 184, 255))

    return bg.convert("RGB")


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "screenshots" / "cover-image.jpeg"
    draw_banner().save(out, format="JPEG", quality=95, optimize=True)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
