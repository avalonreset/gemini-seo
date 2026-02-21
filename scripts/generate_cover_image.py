#!/usr/bin/env python3
"""Generate the Codex SEO repository cover image."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


WIDTH = 1792
HEIGHT = 598


def load_font(size: int, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = []
    if mono:
        font_candidates.extend(
            [
                "C:/Windows/Fonts/consola.ttf",
                "C:/Windows/Fonts/consolab.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            ]
        )
    else:
        font_candidates.extend(
            [
                "C:/Windows/Fonts/segoeuib.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )

    for candidate in font_candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_gradient() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), "#090f16")
    px = img.load()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            fx = x / WIDTH
            fy = y / HEIGHT
            r = int(8 + 10 * fx + 6 * fy)
            g = int(14 + 20 * fx + 6 * (1 - fy))
            b = int(24 + 26 * (1 - fx) + 8 * fy)
            px[x, y] = (r, g, b)
    return img


def draw_glow(base: Image.Image, center: tuple[int, int], radius: int, color: tuple[int, int, int, int]) -> None:
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    x, y = center
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius // 2))
    base.alpha_composite(overlay)


def draw() -> Image.Image:
    bg = make_gradient().convert("RGBA")

    # Atmospheric glows
    draw_glow(bg, (430, 210), 260, (22, 185, 190, 95))
    draw_glow(bg, (1270, 130), 210, (57, 129, 255, 80))
    draw_glow(bg, (1450, 500), 250, (12, 109, 156, 70))

    # Subtle center vignette
    vignette = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    vd.rectangle((0, 0, WIDTH, HEIGHT), fill=(0, 0, 0, 35))
    vd.ellipse((170, 80, WIDTH - 120, HEIGHT - 40), fill=(0, 0, 0, 0))
    vignette = vignette.filter(ImageFilter.GaussianBlur(30))
    bg.alpha_composite(vignette)

    d = ImageDraw.Draw(bg)

    # Left glass panel
    d.rounded_rectangle((54, 34, 920, 560), radius=28, fill=(8, 13, 22, 165), outline=(67, 175, 190, 130), width=2)

    title_font = load_font(152, mono=True)
    sub_title_font = load_font(146, mono=True)
    meta_font = load_font(60)
    label_font = load_font(32, mono=True)
    right_title_font = load_font(52, mono=True)
    right_line_font = load_font(30, mono=True)
    footer_font = load_font(28, mono=True)

    # Title with glow/shadow layers
    for dx, dy, col in [(-3, -3, (8, 18, 32, 210)), (3, 3, (8, 18, 32, 210)), (0, 0, (167, 255, 250, 255))]:
        d.text((88 + dx, 56 + dy), "CODEX", font=title_font, fill=col)
    for dx, dy, col in [(-3, -3, (8, 18, 32, 210)), (3, 3, (8, 18, 32, 210)), (0, 0, (134, 236, 255, 255))]:
        d.text((88 + dx, 202 + dy), "SEO", font=sub_title_font, fill=col)

    d.line((86, 372, 866, 372), fill=(119, 224, 238, 230), width=6)
    d.text((88, 406), "AI-POWERED SEO ANALYSIS", font=meta_font, fill=(230, 246, 255, 245))

    d.rounded_rectangle((86, 490, 868, 544), radius=12, fill=(13, 24, 35, 210), outline=(78, 183, 198, 170), width=2)
    d.text((112, 504), "CODEX-FIRST  |  RUNNER-READY  |  SECURITY-HARDENED", font=label_font, fill=(170, 242, 250, 255))

    # Right command panel
    d.rounded_rectangle((968, 34, 1738, 560), radius=26, fill=(8, 12, 20, 175), outline=(76, 170, 230, 130), width=2)
    d.text((1000, 62), "WORKFLOW ENTRYPOINTS", font=right_title_font, fill=(184, 223, 255, 250))
    d.line((1000, 128, 1708, 128), fill=(97, 167, 255, 220), width=4)

    lines = [
        "seo-audit <url>",
        "seo-page <url>",
        "seo-technical <url>",
        "seo-content <url>",
        "seo-schema analyze|generate",
        "seo-sitemap analyze|generate",
        "seo-geo <url>",
        "seo-images <url>",
        "seo-hreflang validate|generate",
        "seo-programmatic analyze|plan",
        "seo-competitor-pages <mode>",
        "seo-plan <industry>",
    ]
    y = 154
    for line in lines:
        d.text((1002, y), f"> {line}", font=right_line_font, fill=(203, 228, 255, 238))
        y += 31

    d.text((1002, 536), "codex-seo // deterministic runners + skill orchestration", font=footer_font, fill=(143, 195, 235, 255))

    return bg.convert("RGB")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_path = root / "screenshots" / "cover-image.jpeg"
    image = draw()
    image.save(out_path, format="JPEG", quality=95, optimize=True)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
