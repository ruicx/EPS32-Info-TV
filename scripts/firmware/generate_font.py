"""Download the pinned Maple Mono release and generate the production LVGL font.

Notes
-----
Uses Python's standard library and the npm-pinned LVGL converter. Downloaded
inputs and npm packages are cached under the repository's ignored build directory.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile


def verify_hash(path: Path, expected: str) -> None:
    """Verify one cached or extracted input against its pinned SHA-256.

    Parameters
    ----------
    path : Path
        Input file to verify.
    expected : str
        Expected lowercase hexadecimal digest.

    Raises
    ------
    RuntimeError
        If the input does not match the pinned release.
    """
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise RuntimeError(f"SHA-256 mismatch: {path}")


def main() -> None:
    """Download verified inputs and atomically publish a converted C asset.

    Raises
    ------
    RuntimeError
        If Node.js/npm is missing or an input fails its checksum.
    subprocess.CalledProcessError
        If the LVGL converter fails.
    OSError
        If downloading or writing an asset fails.
    """
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "firmware/main/ui/fonts/font_maple_mono_16.c")
    parser.add_argument("--range", default="0x20-0x10FFFF")
    args = parser.parse_args()
    npx = shutil.which("npx.cmd" if sys.platform == "win32" else "npx")
    if npx is None:
        raise RuntimeError("Font generation requires Node.js/npm (npx was not found)")

    cache = root / "build/fonts/upstream"
    cache.mkdir(parents=True, exist_ok=True)
    archive_path = cache / "MapleMono-NF-CN.zip"
    archive_hash = "af913b6322905348b3f50e4397fedc35b3a880db5effcce7969003051dcd3e94"
    if not archive_path.exists():
        download = archive_path.with_suffix(".zip.download")
        url = "https://github.com/subframe7536/maple-font/releases/download/v7.9/MapleMono-NF-CN.zip"
        with urlopen(url) as response, download.open("wb") as destination:
            shutil.copyfileobj(response, destination)
        verify_hash(download, archive_hash)
        download.replace(archive_path)
    verify_hash(archive_path, archive_hash)

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source = cache / "MapleMono-NF-CN-Regular.ttf"
    with ZipFile(archive_path) as archive:
        source.write_bytes(archive.read(source.name))
        (output.parent / "OFL.txt").write_bytes(archive.read("LICENSE.txt"))
    source_hash = "bb8e8e8c263896f42555107202f1847f7a42c340a3e532df9c4d585c9794411c"
    verify_hash(source, source_hash)

    temporary = output.with_suffix(".c.tmp")
    # Fixed advances need no kerning; avoid the converter's pairwise glyph scan.
    subprocess.run(
        [npx, "--yes", "--cache", str(root / "build/npm-cache"),
         "--package", "lv_font_conv@1.5.3", "--", "lv_font_conv",
         "--font", source.name, "--size", "16", "--bpp", "4",
         "--no-compress", "--no-kerning", "--range", args.range,
         "--format", "lvgl", "--lv-include", "lvgl.h",
         "--lv-font-name", "font_maple_mono_16", "--output", str(temporary)],
        cwd=cache,
        check=True,
    )
    # Keep the converter's header stable across output paths and platforms.
    generated = temporary.read_text(encoding="utf-8")
    generated = generated.replace(str(temporary), "font_maple_mono_16.c").rstrip() + "\n"
    temporary.write_text(generated, encoding="utf-8", newline="\n")
    temporary.replace(output)
    print(f"Generated: {output}")
    print(f"Source SHA-256: {source_hash}")


if __name__ == "__main__":
    main()
