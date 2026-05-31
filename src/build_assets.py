#!/usr/bin/env python3
"""
build_assets.py -- one-off generator for Mosquito Watch brand raster assets.

Run locally once (requires Pillow); the outputs are committed and served as static files. The
scheduled build does NOT regenerate them, so this never runs on the (font-less) CI runner.

Outputs into assets/img/:
  favicon.ico            16/32/48 multi-size
  apple-touch-icon.png   180x180
  icon-192.png           192x192     (PWA manifest)
  icon-512.png           512x512
  icon-maskable-512.png  512x512      (full-bleed, marker kept inside the safe zone)
  og-mosquito-watch.png  1200x630     (Open Graph / Twitter share card)

Brand: PharmEasy teal #10847E with a white target marker that echoes the map dots. This is a
clean placeholder; swap for a brand-team asset before launch (see the pharmeasy-branding note).
"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "assets", "img")
TEAL = (16, 132, 126)
TEAL_TOP = (16, 132, 126)
TEAL_BOT = (10, 93, 89)
WHITE = (255, 255, 255)
WINFONTS = "C:/Windows/Fonts"
BOLD = ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
REG = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]


def font(size, bold=True):
    for name in (BOLD if bold else REG):
        for path in (os.path.join(WINFONTS, name), name):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def marker(d, cx, cy, r, color=WHITE, ring=None):
    ring = ring or color
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ring, width=max(3, int(r * 0.33)))
    rr = int(r * 0.33)
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color)


def app_icon(size, maskable=False):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        d.rectangle([0, 0, size, size], fill=TEAL)
        marker(d, size // 2, size // 2, int(size * 0.26))
    else:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=TEAL)
        marker(d, size // 2, size // 2, int(size * 0.30))
    return img


def pill(d, x, y, text, fnt, h=54, pad=24):
    bb = d.textbbox((0, 0), text, font=fnt)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    w = tw + pad * 2
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=(255, 255, 255, 36), outline=(255, 255, 255, 140), width=2)
    d.text((x + pad, y + (h - th) // 2 - bb[1]), text, font=fnt, fill=WHITE)
    return w


def og_image():
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), TEAL)
    d = ImageDraw.Draw(img, "RGBA")
    for i in range(H):                                   # clean vertical teal gradient
        t = i / (H - 1)
        d.line([(0, i), (W, i)], fill=tuple(int(TEAL_TOP[k] + (TEAL_BOT[k] - TEAL_TOP[k]) * t) for k in range(3)))
    marker(d, 1055, 175, 140, color=(255, 255, 255, 26), ring=(255, 255, 255, 38))   # faint motif, top-right
    marker(d, 90, 92, 20, color=WHITE)                                                # brand row
    d.text((128, 72), "PharmEasy", font=font(36, True), fill=WHITE)
    d.text((80, 205), "Mosquito Watch", font=font(94, True), fill=WHITE)
    d.text((84, 332), "Dengue, malaria and chikungunya risk across India", font=font(39, False), fill=(231, 246, 244))
    px, f = 84, font(27, True)
    for label in ["Breeding weather", "Fever signal", "Confirmed cases"]:
        px += pill(d, px, 412, label, f) + 16
    d.text((84, 548), "A weather-based screening guide, not a case forecast or medical advice.",
           font=font(26, False), fill=(206, 232, 229))
    img.save(os.path.join(IMG, "og-mosquito-watch.png"), "PNG")


def main():
    os.makedirs(IMG, exist_ok=True)
    app_icon(180).save(os.path.join(IMG, "apple-touch-icon.png"))
    app_icon(192).save(os.path.join(IMG, "icon-192.png"))
    app_icon(512).save(os.path.join(IMG, "icon-512.png"))
    app_icon(512, maskable=True).save(os.path.join(IMG, "icon-maskable-512.png"))
    app_icon(64).save(os.path.join(IMG, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])
    og_image()
    print("build_assets: wrote favicon.ico, apple-touch-icon, icon-192/512/maskable, og-mosquito-watch.png")


if __name__ == "__main__":
    main()
