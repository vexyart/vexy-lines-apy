# this_file: vexy-lines-apy/src/vexy_lines_api/bundle.py
"""Export a .lines document to multiple formats plus its embedded source image.

One call produces the full asset bundle for a document: vector exports
(PDF, SVG) via the app's MCP API, a PNG rasterized locally from the SVG
(the app's MCP PNG export is unreliable — see issues/703-mcp-png-export.md),
and the embedded source image extracted as ``<stem>-src.jpg`` without
needing the app at all.
"""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from vexy_lines import extract_source_image
from vexy_lines_api.client import MCPClient

DEFAULT_FORMATS = ("pdf", "svg", "png")
SOURCE_SUFFIX = "-src.jpg"


def export_bundle(
    input_path: str | Path,
    output_dir: str | Path | None = None,
    formats: tuple[str, ...] = DEFAULT_FORMATS,
    *,
    source: bool = True,
    dpi: int | None = None,
    render_timeout: float = 600.0,
    client: MCPClient | None = None,
) -> dict[str, Path]:
    """Export a .lines file to several formats and extract its source image.

    Opens the document in the Vexy Lines app (via MCP), renders it, exports
    each requested format, and extracts the embedded source raster as
    ``<stem>-src.jpg``. PNG output is rasterized locally from the exported
    SVG so it works even where the app's raster export does not.

    Args:
        input_path: Path to the ``.lines`` file.
        output_dir: Destination directory. Defaults to the input's directory.
        formats: Any of ``"pdf"``, ``"svg"``, ``"png"``.
        source: Also extract the embedded source image as ``<stem>-src.jpg``.
        dpi: Override document DPI for vector exports.
        render_timeout: Maximum seconds to wait for the document render.
        client: An already-connected :class:`MCPClient` to reuse. When
            ``None``, a client is created for the duration of the call.

    Returns:
        Mapping of output kind (``"pdf"``, ``"svg"``, ``"png"``, ``"source"``)
        to the written file path.

    Raises:
        ValueError: On an unsupported format name.
        MCPError: If the app cannot be reached or an export tool fails.
    """
    src = Path(input_path).expanduser().resolve()
    if not src.is_file():
        # open_document does not fail loudly on a missing path; the app would
        # silently export whatever document is currently active instead.
        msg = f"No such .lines file: {src}"
        raise FileNotFoundError(msg)
    out_dir = Path(output_dir).expanduser().resolve() if output_dir is not None else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    unknown = set(formats) - set(DEFAULT_FORMATS)
    if unknown:
        msg = f"Unsupported formats: {sorted(unknown)}. Choose from {DEFAULT_FORMATS}."
        raise ValueError(msg)

    results: dict[str, Path] = {}

    if formats:
        if client is not None:
            _export_formats(client, src, out_dir, formats, dpi, render_timeout, results)
        else:
            with MCPClient() as own_client:
                _export_formats(own_client, src, out_dir, formats, dpi, render_timeout, results)

    if source:
        dest = out_dir / f"{src.stem}{SOURCE_SUFFIX}"
        results["source"] = extract_source_image(src, dest)
        logger.debug("Extracted source image to {}", dest)

    return results


def _export_formats(
    client: MCPClient,
    src: Path,
    out_dir: Path,
    formats: tuple[str, ...],
    dpi: int | None,
    render_timeout: float,
    results: dict[str, Path],
) -> None:
    """Open, render, and export *src* to each format in *formats*."""
    from vexy_lines_api.export.io import save_svg_as_image  # noqa: PLC0415

    # A render can outlast the server-side timeout, leaving the app's main
    # thread busy; replies to subsequent export calls are then delayed far
    # beyond the default socket timeout. Disconnecting mid-request crashes
    # the app (issues/vl197.md), so widen the socket timeout for the whole
    # export sequence.
    sock = client._sock  # noqa: SLF001
    if sock is not None:
        sock.settimeout(render_timeout + 60.0)
    client.open_document(str(src))
    client.render(timeout=render_timeout)

    svg_text: str | None = None

    if "pdf" in formats:
        pdf_path = client.export_pdf(str(out_dir / f"{src.stem}.pdf"), dpi=dpi)
        _wait_for_file(pdf_path)
        results["pdf"] = pdf_path
    if "svg" in formats or "png" in formats:
        svg_path = out_dir / f"{src.stem}.svg"
        client.export_svg(str(svg_path), dpi=dpi)
        _wait_for_file(svg_path)
        svg_text = svg_path.read_text(encoding="utf-8")
        if "svg" in formats:
            results["svg"] = svg_path
        else:
            svg_path.unlink(missing_ok=True)
    if "png" in formats and svg_text is not None:
        png_path = out_dir / f"{src.stem}.png"
        save_svg_as_image(svg_text, png_path, "PNG")
        results["png"] = png_path


def _wait_for_file(path: Path, timeout: float = 30.0, poll: float = 0.2) -> None:
    """Wait until *path* exists with a stable non-zero size.

    The app replies "Export started" before the file write necessarily
    completes, so exports must be awaited before reading or returning.

    Raises:
        TimeoutError: If the file does not stabilize within *timeout* seconds.
    """
    deadline = time.monotonic() + timeout
    last_size = -1
    while time.monotonic() < deadline:
        if path.exists():
            size = path.stat().st_size
            if size > 0 and size == last_size:
                return
            last_size = size
        time.sleep(poll)
    msg = f"Export did not complete within {timeout:.0f}s: {path}"
    raise TimeoutError(msg)
