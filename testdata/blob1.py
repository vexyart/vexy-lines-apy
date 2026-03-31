#!/usr/bin/env python3
# this_file: vexy-lines-apy/testdata/blob1.py
"""Apply blob2.lines style onto blob1a.png using the fast-path XML swap.

Uses apply_style() which detects matching dimensions and swaps the source
image at the XML level, then opens the modified .lines in Vexy Lines.

Requires the Vexy Lines app to be running (MCP server on localhost:47384).

Usage::

    python testdata/blob1.py
"""

from pathlib import Path

from loguru import logger

from vexy_lines_api import MCPClient, apply_style, extract_style

TESTDATA = Path(__file__).parent
STYLE_FILE = TESTDATA / "blob2.lines"
NEW_IMAGE = TESTDATA / "blob1a.png"
OUT_PNG = TESTDATA / "blob1.png"


def main() -> None:
    logger.info("Extracting style from {}", STYLE_FILE.name)
    style = extract_style(STYLE_FILE)
    logger.info(
        "Style: {} groups/layers, {}x{} mm @ {}dpi",
        len(style.groups),
        style.props.width_mm,
        style.props.height_mm,
        style.props.dpi,
    )

    logger.info("Applying style to {} (should use fast path)", NEW_IMAGE.name)
    with MCPClient() as client:
        svg_text = apply_style(client, style, NEW_IMAGE, dpi=style.props.dpi, render_timeout=300)

    logger.info("Got SVG: {:.1f} KB, {} paths", len(svg_text) / 1024, svg_text.count("<path"))

    # Rasterize SVG to PNG
    from vexy_lines_api.video import svg_to_pil

    img = svg_to_pil(svg_text, 1024, 1024)
    img.save(str(OUT_PNG))
    logger.info("Saved {}", OUT_PNG.name)

    logger.info("Done")


if __name__ == "__main__":
    main()
