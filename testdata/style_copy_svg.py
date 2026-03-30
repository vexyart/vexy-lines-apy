#!/usr/bin/env python3
# this_file: vexy-lines-apy/testdata/style_copy_svg.py
"""Copy the style from beara-01.lines onto beara-01/02.jpg and export as SVG.

Requires the Vexy Lines app to be running (MCP server on localhost:47384).

Usage::

    python testdata/style_copy_svg.py
"""

from pathlib import Path

from loguru import logger

from vexy_lines_api import MCPClient, apply_style, extract_style

TESTDATA = Path(__file__).parent
STYLE_FILE = TESTDATA / "beara-01.lines"
IMAGES = [TESTDATA / f"beara-0{i}.jpg" for i in (1, 2)]
OUTPUT_DIR = TESTDATA


def main() -> None:
    logger.info("Extracting style from {}", STYLE_FILE.name)
    style = extract_style(STYLE_FILE)
    logger.info(
        "Style: {} groups/layers, thickness range {}-{}, interval range {}-{}",
        len(style.groups),
        style.props.thickness_min,
        style.props.thickness_max,
        style.props.interval_min,
        style.props.interval_max,
    )

    for image_path in IMAGES:
        if not image_path.exists():
            logger.warning("Skipping {} (not found)", image_path.name)
            continue

        out_path = OUTPUT_DIR / f"{image_path.stem}-styled.svg"
        logger.info("Applying style to {} -> {}", image_path.name, out_path.name)

        with MCPClient() as client:
            svg = apply_style(client, style, image_path, render_timeout=300)

        out_path.write_text(svg, encoding="utf-8")
        logger.info("Wrote {} ({:.1f} KB)", out_path.name, len(svg) / 1024)

    logger.info("Done")


if __name__ == "__main__":
    main()
