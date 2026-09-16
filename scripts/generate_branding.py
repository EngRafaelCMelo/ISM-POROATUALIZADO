"""Gera derivados determinísticos da marca oficial sem redesenhar a arte."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageChops


def content_bbox(image: Image.Image, threshold: int = 246) -> tuple[int, int, int, int]:
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, "white")
    difference = ImageChops.difference(rgb, background).convert("L")
    mask = difference.point(lambda value: 255 if value > 255 - threshold else 0)
    return mask.getbbox() or (0, 0, image.width, image.height)


def green_symbol_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    rgb = image.convert("RGB")
    mask = Image.new("L", rgb.size)
    mask.putdata([255 if green > red * 1.12 and green > blue * 1.08 and green > 55 else 0 for red, green, blue in rgb.getdata()])
    return mask.getbbox() or content_bbox(image)


def padded_crop(image: Image.Image, bbox: tuple[int, int, int, int], padding: int) -> Image.Image:
    left, top, right, bottom = bbox
    return image.crop((max(0, left - padding), max(0, top - padding), min(image.width, right + padding), min(image.height, bottom + padding)))


def white_to_alpha(image: Image.Image, start: int = 238) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = []
    for red, green, blue, _ in rgba.getdata():
        distance = 255 - min(red, green, blue)
        alpha = 0 if min(red, green, blue) >= 252 else min(255, max(0, round(distance * 255 / (255 - start))))
        pixels.append((red, green, blue, alpha))
    rgba.putdata(pixels)
    return rgba


def fit_canvas(image: Image.Image, size: tuple[int, int], transparent: bool) -> Image.Image:
    canvas = Image.new("RGBA" if transparent else "RGB", size, (255, 255, 255, 0) if transparent else "white")
    copy = image.copy(); copy.thumbnail((size[0] - 48, size[1] - 48), Image.Resampling.LANCZOS)
    canvas.paste(copy, ((size[0] - copy.width) // 2, (size[1] - copy.height) // 2), copy if copy.mode == "RGBA" else None)
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    destination = args.destination; source_dir = destination / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    preserved = source_dir / "ism_logo_original.jpeg"
    shutil.copy2(args.source, preserved)
    original = Image.open(preserved).convert("RGB")

    horizontal = padded_crop(original, content_bbox(original), 36)
    horizontal.save(destination / "ism_logo_horizontal.png", optimize=True)
    horizontal_transparent = white_to_alpha(horizontal)
    horizontal_transparent.save(destination / "ism_logo_horizontal_transparente.png", optimize=True)

    left_region = original.crop((0, 0, round(original.width * 0.46), original.height))
    symbol = padded_crop(left_region, green_symbol_bbox(left_region), 34)
    symbol.save(destination / "ism_simbolo.png", optimize=True)
    symbol_transparent = white_to_alpha(symbol)
    symbol_transparent.save(destination / "ism_simbolo_transparente.png", optimize=True)

    icon_master = fit_canvas(symbol_transparent, (256, 256), transparent=True)
    icon_master.save(
        destination / "ism_app_icon.ico", format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    main()
