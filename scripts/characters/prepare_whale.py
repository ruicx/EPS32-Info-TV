"""Prepare full-body idle, blink, and weight-shift whale companion frames.

Notes
-----
Extracts frames from the pinned upstream sheets, trims transparent margins,
resamples onto an 80x84 canvas anchored at y=82, and exports preview PNGs
and LVGL 9.3 straight-alpha ARGB8888 C source files.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import urllib.request
from pathlib import Path

from PIL import Image

IDLE_FRONT_URL = (
    "https://raw.githubusercontent.com/YunYueSama/codex-deepseek-pet/"
    "7661c8b304c5400701f91da01b1a643a207331de/assets/whale/idle-front.png"
)
IDLE_FRONT_SHA256 = (
    "79d3952acfe7620e0c2cfe7b80e9e6793d5f115252962f81cd56778402f4cdcd"
)

DENSE_IDLE_URL = (
    "https://raw.githubusercontent.com/YunYueSama/codex-deepseek-pet/"
    "7661c8b304c5400701f91da01b1a643a207331de/assets/whale/dense-idle.png"
)
DENSE_IDLE_SHA256 = (
    "fdd3990fee0302d41d9809007f1303663440af299e0ff979e3b67bd777d934ef"
)

CANVAS_WIDTH = 80
CANVAS_HEIGHT = 84
MAX_BOUND_WIDTH = 76.0
MAX_BOUND_HEIGHT = 80.0
FOOT_ANCHOR_Y = 82
ALPHA_THRESHOLD = 8


def verify_hash(path: Path, expected: str) -> None:
    """Verify an input file against its pinned SHA-256 digest.

    Parameters
    ----------
    path : Path
        Path to the file to verify.
    expected : str
        Expected lowercase hexadecimal digest.

    Raises
    ------
    RuntimeError
        If the SHA-256 checksum does not match.
    """
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual.lower() != expected.lower():
        raise RuntimeError(f"SHA-256 mismatch for {path}: got {actual}, expected {expected}")


def ensure_asset(path: Path | None, fallback_cache: Path, url: str, expected_hash: str) -> Path:
    """Resolve an asset path, downloading and caching if omitted.

    Parameters
    ----------
    path : Path | None
        Explicit file path provided by user, if any.
    fallback_cache : Path
        Local cache path if file needs to be downloaded.
    url : str
        Upstream download URL.
    expected_hash : str
        Pinned SHA-256 digest.

    Returns
    -------
    Path
        Verified path to the source asset.

    Raises
    ------
    RuntimeError
        If verification or download fails.
    """
    if path is not None and path.is_file():
        verify_hash(path, expected_hash)
        return path

    fallback_cache.parent.mkdir(parents=True, exist_ok=True)
    if not fallback_cache.exists():
        downloading = fallback_cache.with_suffix(".tmp")
        print(f"Downloading {url} ...")
        with urllib.request.urlopen(url) as response, downloading.open("wb") as destination:
            shutil.copyfileobj(response, destination)
        verify_hash(downloading, expected_hash)
        downloading.replace(fallback_cache)
    verify_hash(fallback_cache, expected_hash)
    return fallback_cache


def find_crop_bounds(image: Image.Image, threshold: int = ALPHA_THRESHOLD) -> tuple[int, int, int, int]:
    """Calculate the bounding box of pixels exceeding the alpha threshold.

    Parameters
    ----------
    image : Image.Image
        Source RGBA image tile.
    threshold : int
        Minimum alpha value (0-255) to consider opaque.

    Returns
    -------
    tuple[int, int, int, int]
        Bounding box tuple (left, top, right, bottom).

    Raises
    ------
    ValueError
        If no pixels exceed the threshold.
    """
    alpha = image.getchannel("A")
    mask = alpha.point(lambda p: 255 if p > threshold else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise ValueError("Image contains no pixels exceeding alpha threshold.")
    return bbox


def export_character_frame(
    source: Image.Image,
    tile_box: tuple[int, int, int, int],
    name: str,
    output_directory: Path,
) -> None:
    """Trim, scale, and anchor one frame, exporting both PNG and C source.

    Parameters
    ----------
    source : Image.Image
        Full sprite sheet image.
    tile_box : tuple[int, int, int, int]
        Bounding box of the tile in the sprite sheet (left, top, right, bottom).
    name : str
        Base name for output files and the C symbol (e.g. whale_idle).
    output_directory : Path
        Directory where outputs are written.

    Returns
    -------
    None
    """
    tile = source.crop(tile_box).convert("RGBA")
    crop_box = find_crop_bounds(tile)
    cropped = tile.crop(crop_box)

    crop_width = crop_box[2] - crop_box[0]
    crop_height = crop_box[3] - crop_box[1]

    scale = min(MAX_BOUND_WIDTH / crop_width, MAX_BOUND_HEIGHT / crop_height)
    target_width = round(crop_width * scale)
    target_height = round(crop_height * scale)

    resized = cropped.resize((target_width, target_height), resample=Image.Resampling.BICUBIC)

    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    paste_x = int((CANVAS_WIDTH - target_width) / 2)
    paste_y = FOOT_ANCHOR_Y - target_height
    canvas.paste(resized, (paste_x, paste_y), resized)

    output_directory.mkdir(parents=True, exist_ok=True)
    png_path = output_directory / f"{name}.png"
    canvas.save(png_path, format="PNG")

    c_path = output_directory / f"{name}.c"
    raw_rgba = canvas.tobytes()
    bytes_per_row = CANVAS_WIDTH * 4

    lines: list[str] = [
        "/** Generated by scripts/characters/prepare_whale.py; see assets/README.md for attribution. */",
        '#include "lvgl.h"',
        "",
        "static const uint8_t pixels[] = {",
    ]

    for y in range(CANVAS_HEIGHT):
        row_offset = y * bytes_per_row
        row_values: list[str] = []
        for x in range(CANVAS_WIDTH):
            offset = row_offset + x * 4
            r = raw_rgba[offset]
            g = raw_rgba[offset + 1]
            b = raw_rgba[offset + 2]
            a = raw_rgba[offset + 3]
            for val in (b, g, r, a):
                row_values.append(f"0x{val:02x}")
        lines.append("  " + ", ".join(row_values) + ",")

    lines.extend([
        "};",
        "",
        "/** Full-body pose in straight-alpha BGRA, shared by device and desktop. */",
        f"const lv_image_dsc_t {name} = {{",
        "  .header = {.magic = LV_IMAGE_HEADER_MAGIC, .cf = LV_COLOR_FORMAT_ARGB8888,",
        "             .w = 80, .h = 84, .stride = 320},",
        "  .data_size = sizeof(pixels), .data = pixels,",
        "};",
        "",
    ])

    c_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"Exported: {name}.png and {name}.c")


def main() -> None:
    """CLI entry point to prepare whale character assets.

    Returns
    -------
    None

    Raises
    ------
    RuntimeError
        If required assets or checksum validation fails.
    """
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Optional local path to upstream idle-front.png.",
    )
    parser.add_argument(
        "--motion-source",
        type=Path,
        default=None,
        help="Optional local path to upstream dense-idle.png.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "firmware/main/ui/assets",
        help="Directory where output .png and .c files will be written.",
    )
    args = parser.parse_args()

    cache_dir = repo_root / "build/character-cache/whale"
    idle_path = ensure_asset(
        args.source,
        cache_dir / "idle-front.png",
        IDLE_FRONT_URL,
        IDLE_FRONT_SHA256,
    )
    motion_path = ensure_asset(
        args.motion_source,
        cache_dir / "dense-idle.png",
        DENSE_IDLE_URL,
        DENSE_IDLE_SHA256,
    )

    with Image.open(idle_path) as idle_img, Image.open(motion_path) as motion_img:
        frame_width = int(idle_img.width / 2)
        export_character_frame(
            idle_img,
            (0, 0, frame_width, idle_img.height),
            "whale_idle",
            args.output_dir,
        )
        export_character_frame(
            idle_img,
            (frame_width, 0, frame_width * 2, idle_img.height),
            "whale_closed",
            args.output_dir,
        )

        frames = (1, 3, 5, 7)
        for index, frame in enumerate(frames):
            col = frame % 4
            row = frame // 4
            tile_box = (col * 512, row * 512, (col + 1) * 512, (row + 1) * 512)
            export_character_frame(
                motion_img,
                tile_box,
                f"whale_shift_{index}",
                args.output_dir,
            )

    print("Whale frames preparation complete.")


if __name__ == "__main__":
    main()
