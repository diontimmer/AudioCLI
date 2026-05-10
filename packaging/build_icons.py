"""Generate platform icon files (.icns, .ico, .png) from packaging/icon.svg.

Renderer priority (first one available wins):
    1. rsvg-convert        — `brew install librsvg`        (preferred)
    2. cairosvg            — `pip install cairosvg`        (needs system cairo)

On macOS the .icns file is built via the system `iconutil` binary.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGING = Path(__file__).resolve().parent
SVG = PACKAGING / "icon.svg"


def _render_with_rsvg(size: int) -> bytes | None:
    if shutil.which("rsvg-convert") is None:
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        subprocess.run(
            [
                "rsvg-convert",
                "-w", str(size),
                "-h", str(size),
                "-o", str(tmp_path),
                str(SVG),
            ],
            check=True,
        )
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def _render_with_cairosvg(size: int) -> bytes | None:
    try:
        import cairosvg  # type: ignore[import-not-found]
    except (ImportError, OSError):
        return None
    return cairosvg.svg2png(
        url=str(SVG),
        output_width=size,
        output_height=size,
    )


def _render_png(size: int) -> bytes:
    for renderer in (_render_with_rsvg, _render_with_cairosvg):
        png = renderer(size)
        if png is not None:
            return png
    sys.stderr.write(
        "ERROR: no SVG renderer available. Install one of:\n"
        "  brew install librsvg          (recommended)\n"
        "  brew install cairo && pip install cairosvg\n"
    )
    raise SystemExit(1)


def build_icns() -> Path | None:
    if sys.platform != "darwin":
        print("skipping .icns (macOS only)")
        return None
    if shutil.which("iconutil") is None:
        print("ERROR: iconutil not found — install Xcode Command Line Tools", file=sys.stderr)
        return None

    iconset = PACKAGING / "AudioCLI.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()

    layout = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for size, name in layout:
        (iconset / name).write_bytes(_render_png(size))

    icns = PACKAGING / "icon.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", "-o", str(icns), str(iconset)],
        check=True,
    )
    shutil.rmtree(iconset)
    print(f"wrote {icns}")
    return icns


def build_ico() -> Path:
    from PIL import Image

    sizes = [16, 24, 32, 48, 64, 128, 256]
    rendered = [Image.open(io.BytesIO(_render_png(size))) for size in sizes]
    ico = PACKAGING / "icon.ico"
    rendered[0].save(ico, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"wrote {ico}")
    return ico


def build_png_master() -> Path:
    """Also drop a 1024px PNG for Linux desktop entries / docs."""
    png = PACKAGING / "icon.png"
    png.write_bytes(_render_png(1024))
    print(f"wrote {png}")
    return png


if __name__ == "__main__":
    build_icns()
    build_ico()
    build_png_master()
