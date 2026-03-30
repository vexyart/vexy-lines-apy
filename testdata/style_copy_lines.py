#!/usr/bin/env python3
# this_file: vexy-lines-apy/testdata/style_copy_lines.py
"""Copy the style from beara-01.lines onto beara-01/02.jpg and save as .lines files.

Creates styled documents without rendering or SVG export — just builds
the document structure and saves as .lines.

Requires the Vexy Lines app to be running (MCP server on localhost:47384).

Usage::

    python testdata/style_copy_lines.py
"""

from pathlib import Path

from loguru import logger

from vexy_lines_api import MCPClient, create_styled_document, extract_style, save_and_consolidate

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

        out_path = OUTPUT_DIR / f"{image_path.stem}-styled.lines"
        logger.info("Applying style to {} -> {}", image_path.name, out_path.name)

        with MCPClient() as client:
            create_styled_document(client, style, image_path)
            save_and_consolidate(client, out_path)

        logger.info("Wrote {}", out_path.name)

    logger.info("Done")


if __name__ == "__main__":
    main()
