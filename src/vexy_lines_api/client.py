# this_file: vexy-lines-apy/src/vexy_lines_api/client.py
"""TCP client for the Vexy Lines MCP server (JSON-RPC 2.0).

The Vexy Lines macOS app embeds an MCP server on ``localhost:47384``.
This module speaks newline-delimited JSON-RPC 2.0 over a raw TCP socket,
handles the MCP initialize/initialized handshake, and exposes all 25 tools
as typed Python methods.

Example::

    with MCPClient() as vl:
        info = vl.get_document_info()   # DocumentInfo
        tree = vl.get_layer_tree()      # LayerNode tree
        vl.set_fill_params(fill_id, color="#ff0000")
        vl.render()                     # render + wait
        vl.export_svg("out.svg")
"""

from __future__ import annotations

import contextlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from typing import Self

from vexy_lines_api.types import DocumentInfo, LayerNode, NewDocumentResult, RenderStatus

if TYPE_CHECKING:
    from types import TracebackType

APP_NAME = "Vexy Lines"
MCP_PORT = 47384
PROTOCOL_VERSION = "2024-11-05"


class MCPError(Exception):
    """Raised when the MCP server returns an error or communication fails.

    Attributes:
        message: Human-readable error description.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MCPClient:
    """Context-managed client for the Vexy Lines MCP server.

    Connects via TCP to the embedded JSON-RPC 2.0 server, performs the
    MCP initialize/initialized handshake, and exposes typed methods for
    every supported tool.

    Args:
        host: Server address (default ``127.0.0.1``).
        port: Server port (default 47384).
        timeout: Socket timeout in seconds (default 30).
        auto_launch: If ``True``, attempt to launch the app on connection failure.
    """

    def __init__(
        self, host: str = "127.0.0.1", port: int = MCP_PORT, timeout: float = 30.0, *, auto_launch: bool = True
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._auto_launch = auto_launch
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._request_id = 0

    # -- context manager --------------------------------------------------

    def __enter__(self) -> Self:
        self._connect()
        self._handshake()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._close()

    # -- connection -------------------------------------------------------

    def _connect(self) -> None:
        """Open TCP socket to the MCP server, launching the app if needed."""
        try:
            self._try_connect()
        except MCPError:
            if not self._auto_launch:
                raise
            self._launch_app()
            self._wait_for_server()

    def _try_connect(self) -> None:
        """Single connection attempt."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self._timeout)
        try:
            self._sock.connect((self._host, self._port))
        except OSError as exc:
            self._sock.close()
            self._sock = None
            msg = f"Cannot connect to {APP_NAME} MCP server at {self._host}:{self._port}: {exc}"
            raise MCPError(msg) from exc

    def _launch_app(self) -> None:
        """Launch the Vexy Lines app on macOS or Windows.

        Raises:
            MCPError: On Windows if the executable is not found in standard
                install locations, or on unsupported platforms.
        """
        if sys.platform == "darwin":
            subprocess.run(  # noqa: S603
                ["open", "-a", APP_NAME],  # noqa: S607
                capture_output=True,
                timeout=10,
                check=False,
            )
        elif sys.platform == "win32":
            app_path = None
            for candidate in [
                Path("C:/Program Files/Vexy Lines/Vexy Lines.exe"),
                Path("C:/Program Files (x86)/Vexy Lines/Vexy Lines.exe"),
                Path.home() / "AppData/Local/Programs/Vexy Lines/Vexy Lines.exe",
            ]:
                if candidate.exists():
                    app_path = candidate
                    break
            if app_path is None:
                msg = f"{APP_NAME} not found. Install it or pass auto_launch=False and start it manually."
                raise MCPError(msg)
            subprocess.Popen([str(app_path)])  # noqa: S603
        else:
            msg = f"Auto-launch not supported on {sys.platform}. Start {APP_NAME} manually."
            raise MCPError(msg)

    def _wait_for_server(self, max_wait: float = 30.0) -> None:
        """Poll until the MCP server accepts connections or the deadline passes.

        Uses gentle exponential back-off (0.5s → 2.0s cap) to avoid hammering
        the socket while the app starts up.

        Args:
            max_wait: Maximum seconds to wait before raising.

        Raises:
            MCPError: If the server is still unreachable after *max_wait* seconds.
        """
        deadline = time.monotonic() + max_wait
        interval = 0.5
        last_error: MCPError | None = None
        while time.monotonic() < deadline:
            try:
                self._try_connect()
                return
            except MCPError as exc:
                last_error = exc
                time.sleep(interval)
                interval = min(interval * 1.2, 2.0)  # gentle backoff
        msg = f"{APP_NAME} launched but MCP server not ready after {max_wait:.0f}s. Last error: {last_error}"
        raise MCPError(msg)

    def _close(self) -> None:
        """Close the TCP socket."""
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.shutdown(socket.SHUT_RDWR)
            self._sock.close()
            self._sock = None

    def _handshake(self) -> None:
        """Run the MCP initialize / initialized handshake."""
        result = self._send_request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "vexy-lines-apy", "version": "1.0.0"},
            },
        )
        server_version = result.get("protocolVersion", "")
        if server_version != PROTOCOL_VERSION:
            msg = f"Protocol mismatch: client={PROTOCOL_VERSION}, server={server_version}"
            raise MCPError(msg)
        self._send_notification("notifications/initialized")

    # -- low-level transport ----------------------------------------------

    def _next_id(self) -> int:
        """Return the next JSON-RPC request ID."""
        self._request_id += 1
        return self._request_id

    def _send_request(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        """Send a JSON-RPC request and return the result.

        Args:
            method: RPC method name.
            params: Optional parameter dict.

        Returns:
            The ``result`` field from the JSON-RPC response.

        Raises:
            MCPError: On transport or server error.
        """
        msg: dict[str, object] = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        self._send_bytes(msg)
        return self._recv_response()

    def _send_notification(self, method: str, params: dict[str, object] | None = None) -> None:
        """Send a JSON-RPC notification (no id, no response expected).

        Args:
            method: RPC method name.
            params: Optional parameter dict.
        """
        msg: dict[str, object] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            msg["params"] = params
        self._send_bytes(msg)

    def _send_bytes(self, msg: dict[str, object]) -> None:
        """Serialize and send a newline-delimited JSON message."""
        if self._sock is None:
            err = "Not connected"
            raise MCPError(err)
        data = json.dumps(msg, separators=(",", ":")) + "\n"
        self._sock.sendall(data.encode("utf-8"))

    def _recv_response(self) -> dict[str, object]:
        """Read next newline-delimited JSON-RPC response from the buffer.

        Returns:
            Parsed ``result`` dict from the response.

        Raises:
            MCPError: On connection close, invalid JSON, or server error.
        """
        if self._sock is None:
            err = "Not connected"
            raise MCPError(err)

        while True:
            newline_pos = self._buffer.find(b"\n")
            if newline_pos != -1:
                line = self._buffer[:newline_pos]
                self._buffer = self._buffer[newline_pos + 1 :]
                break
            chunk = self._sock.recv(4096)
            if not chunk:
                err = "Connection closed by server"
                raise MCPError(err)
            self._buffer += chunk

        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            err = f"Invalid JSON from server: {exc}"
            raise MCPError(err) from exc

        if "error" in response:
            err_obj = response["error"]
            code = err_obj.get("code", -1) if isinstance(err_obj, dict) else -1
            message = err_obj.get("message", "Unknown error") if isinstance(err_obj, dict) else str(err_obj)
            err = f"MCP error {code}: {message}"
            raise MCPError(err)

        result = response.get("result", {})
        return result if isinstance(result, dict) else {}

    # -- tool calling -----------------------------------------------------

    def call_tool(self, name: str, arguments: dict[str, object] | None = None) -> dict[str, object] | str:
        """Call an MCP tool and return the parsed result.

        The server wraps results in ``content[0].text`` which may be JSON or
        plain text. This method attempts JSON parse first, falls back to
        returning the raw string.

        Args:
            name: Tool name (e.g. ``"get_document_info"``).
            arguments: Optional tool arguments dict.

        Returns:
            Parsed dict or raw string from the server.
        """
        params: dict[str, object] = {"name": name}
        if arguments is not None:
            params["arguments"] = arguments
        result = self._send_request("tools/call", params)

        # Extract text from content array
        content = result.get("content", [])
        if not isinstance(content, list) or not content:
            return result

        first = content[0]
        text = first.get("text", "") if isinstance(first, dict) else ""
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else text  # type: ignore[return-value]
        except (json.JSONDecodeError, TypeError):
            return str(text)

    # -- document operations ----------------------------------------------

    def new_document(
        self,
        width: float | None = None,
        height: float | None = None,
        dpi: float = 300,
        source_image: str | None = None,
    ) -> NewDocumentResult:
        """Create a new document.

        Args:
            width: Document width in pixels (optional, inferred from source image).
            height: Document height in pixels (optional, inferred from source image).
            dpi: Document resolution (default 300).
            source_image: Path to a source image file.

        Returns:
            :class:`~vexy_lines_api.types.NewDocumentResult` with document metadata.
        """
        args: dict[str, object] = {"dpi": dpi}
        if width is not None:
            args["width"] = width
        if height is not None:
            args["height"] = height
        if source_image is not None:
            args["source_image"] = str(Path(source_image).expanduser().resolve())
        data = self.call_tool("new_document", args)
        if isinstance(data, str):
            msg = f"Unexpected response from new_document: {data}"
            raise MCPError(msg)
        return NewDocumentResult(
            status=str(data.get("status", "")),
            width=float(data.get("width", 0)),
            height=float(data.get("height", 0)),
            dpi=float(data.get("dpi", 0)),
            root_id=int(data.get("root_id", 0)),
        )

    def open_document(self, path: str) -> str:
        """Open a ``.lines`` document from disk.

        Args:
            path: Path to a ``.lines`` file.

        Returns:
            Server status string.
        """
        result = self.call_tool("open_document", {"path": str(Path(path).expanduser().resolve())})
        return result if isinstance(result, str) else str(result)

    def save_document(self, path: str | None = None) -> str:
        """Save the current document, optionally to a new path.

        Args:
            path: Optional file path to save to (Save As).

        Returns:
            Server status string.
        """
        args: dict[str, object] = {}
        if path is not None:
            args["path"] = str(Path(path).expanduser().resolve())
        result = self.call_tool("save_document", args)
        return result if isinstance(result, str) else str(result)

    def export_document(
        self,
        path: str,
        dpi: int | None = None,
        format: str | None = None,  # noqa: A002
    ) -> str:
        """Export the document to an image file.

        Args:
            path: Output file path.
            dpi: Override document DPI for export.
            format: Export format (``"svg"``, ``"pdf"``, ``"png"``, ``"jpg"``, ``"eps"``).

        Returns:
            Server status string.
        """
        args: dict[str, object] = {"path": str(Path(path).expanduser().resolve())}
        if dpi is not None:
            args["dpi"] = dpi
        if format is not None:
            args["format"] = format
        result = self.call_tool("export_document", args)
        return result if isinstance(result, str) else str(result)

    def get_document_info(self) -> DocumentInfo:
        """Get metadata about the current document.

        Returns:
            :class:`~vexy_lines_api.types.DocumentInfo` with document metadata.
        """
        data = self.call_tool("get_document_info")
        if isinstance(data, str):
            msg = f"Unexpected response from get_document_info: {data}"
            raise MCPError(msg)
        return DocumentInfo(
            width_mm=float(data.get("width_mm", 0)),
            height_mm=float(data.get("height_mm", 0)),
            resolution=float(data.get("resolution", 0)),
            units=str(data.get("units", "")),
            has_changes=bool(data.get("has_changes", False)),
        )

    # -- structure --------------------------------------------------------

    def get_layer_tree(self) -> LayerNode:
        """Get the full document layer tree.

        Returns:
            Root :class:`~vexy_lines_api.types.LayerNode` of the document tree.
        """
        data = self.call_tool("get_layer_tree")
        if isinstance(data, str):
            msg = f"Unexpected response from get_layer_tree: {data}"
            raise MCPError(msg)
        return LayerNode.from_dict(data)

    def add_group(
        self,
        parent_id: int | None = None,
        caption: str | None = None,
        source_image_path: str | None = None,
    ) -> dict[str, object]:
        """Add a new group to the document.

        Args:
            parent_id: Parent object ID (default: document root).
            caption: Group name.
            source_image_path: Optional source image for the group.

        Returns:
            Server response dict (includes ``"id"`` of the created group).
        """
        args: dict[str, object] = {}
        if parent_id is not None:
            args["parent_id"] = parent_id
        if caption is not None:
            args["caption"] = caption
        if source_image_path is not None:
            args["source_image_path"] = source_image_path
        data = self.call_tool("add_group", args)
        return data if isinstance(data, dict) else {"result": data}

    def add_layer(self, group_id: int) -> dict[str, object]:
        """Add a new layer to a group.

        Args:
            group_id: Parent group object ID.

        Returns:
            Server response dict (includes ``"id"`` of the created layer).
        """
        data = self.call_tool("add_layer", {"group_id": group_id})
        return data if isinstance(data, dict) else {"result": data}

    def add_fill(
        self,
        layer_id: int,
        fill_type: str,
        color: str | None = None,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Add a fill to a layer.

        Args:
            layer_id: Parent layer object ID.
            fill_type: Fill type (e.g. ``"linear"``, ``"circular"``).
            color: Hex colour string.
            params: Additional fill parameters.

        Returns:
            Server response dict (includes ``"id"`` of the created fill).
        """
        args: dict[str, object] = {"layer_id": layer_id, "fill_type": fill_type}
        if color is not None:
            args["color"] = color
        if params is not None:
            args["params"] = params
        data = self.call_tool("add_fill", args)
        return data if isinstance(data, dict) else {"result": data}

    def delete_object(self, object_id: int) -> str:
        """Delete an object by ID.

        Args:
            object_id: Object to delete.

        Returns:
            Server status string.
        """
        result = self.call_tool("delete_object", {"id": object_id})
        return result if isinstance(result, str) else str(result)

    # -- fill params ------------------------------------------------------

    def get_fill_params(self, fill_id: int) -> dict[str, object]:
        """Get parameters of a fill.

        Args:
            fill_id: Fill object ID.

        Returns:
            Dict of fill parameter names to values.
        """
        data = self.call_tool("get_fill_params", {"id": fill_id})
        return data if isinstance(data, dict) else {"result": data}

    def set_fill_params(self, fill_id: int, **params: object) -> str:
        """Set fill parameters via keyword arguments.

        Example::

            client.set_fill_params(42, color="#ff0000", interval=20)

        Args:
            fill_id: Fill object ID.
            **params: Parameter names and values to set.  Spatial values
                are in pixels.  ``"color"`` accepts hex or named colour.

        Returns:
            Server status string.
        """
        args: dict[str, object] = {"id": fill_id, "params": dict(params)}
        result = self.call_tool("set_fill_params", args)
        return result if isinstance(result, str) else str(result)

    # -- visual -----------------------------------------------------------

    def set_source_image(self, image_path: str, group_id: int | None = None) -> str:
        """Set the source image for a group.

        Args:
            image_path: Path to the image file.
            group_id: Target group (default: current group).

        Returns:
            Server status string.
        """
        args: dict[str, object] = {"image_path": str(Path(image_path).expanduser().resolve())}
        if group_id is not None:
            args["group_id"] = group_id
        result = self.call_tool("set_source_image", args)
        return result if isinstance(result, str) else str(result)

    def set_caption(self, object_id: int, caption: str) -> str:
        """Set the caption/name of an object.

        Args:
            object_id: Target object ID.
            caption: New caption string.

        Returns:
            Server status string.
        """
        result = self.call_tool("set_caption", {"id": object_id, "caption": caption})
        return result if isinstance(result, str) else str(result)

    def set_visible(self, object_id: int, *, visible: bool) -> str:
        """Set visibility of an object.

        Args:
            object_id: Target object ID.
            visible: Whether the object should be visible.

        Returns:
            Server status string.
        """
        result = self.call_tool("set_visible", {"id": object_id, "visible": visible})
        return result if isinstance(result, str) else str(result)

    def set_layer_mask(self, layer_id: int, paths: list[str], mode: str = "create") -> str:
        """Set a vector mask on a layer.

        Args:
            layer_id: Target layer object ID.
            paths: SVG path data strings for the mask.
            mode: Mask mode (``"create"``, ``"add"``, ``"subtract"``).

        Returns:
            Server status string.
        """
        result = self.call_tool(
            "set_layer_mask",
            {
                "layer_id": layer_id,
                "paths": paths,
                "mode": mode,
            },
        )
        return result if isinstance(result, str) else str(result)

    def get_layer_mask(self, layer_id: int) -> dict[str, object]:
        """Get the vector mask of a layer.

        Args:
            layer_id: Target layer object ID.

        Returns:
            Dict with mask data.
        """
        data = self.call_tool("get_layer_mask", {"layer_id": layer_id})
        return data if isinstance(data, dict) else {"result": data}

    def transform_layer(
        self,
        layer_id: int,
        translate_x: float = 0,
        translate_y: float = 0,
        rotate_deg: float = 0,
        scale_x: float = 1,
        scale_y: float = 1,
    ) -> str:
        """Apply a 2D transform to a layer.

        Args:
            layer_id: Target layer object ID.
            translate_x: Horizontal translation in pixels.
            translate_y: Vertical translation in pixels.
            rotate_deg: Rotation angle in degrees.
            scale_x: Horizontal scale factor.
            scale_y: Vertical scale factor.

        Returns:
            Server status string.
        """
        result = self.call_tool(
            "transform_layer",
            {
                "id": layer_id,
                "translate_x": translate_x,
                "translate_y": translate_y,
                "rotate_deg": rotate_deg,
                "scale_x": scale_x,
                "scale_y": scale_y,
            },
        )
        return result if isinstance(result, str) else str(result)

    def set_layer_warp(
        self,
        layer_id: int,
        top_left: list[float],
        top_right: list[float],
        bottom_right: list[float],
        bottom_left: list[float],
    ) -> str:
        """Set perspective warp corners on a layer.

        Args:
            layer_id: Target layer object ID.
            top_left: ``[x, y]`` coordinates of the top-left corner.
            top_right: ``[x, y]`` coordinates of the top-right corner.
            bottom_right: ``[x, y]`` coordinates of the bottom-right corner.
            bottom_left: ``[x, y]`` coordinates of the bottom-left corner.

        Returns:
            Server status string.
        """
        result = self.call_tool(
            "set_layer_warp",
            {
                "id": layer_id,
                "top_left": top_left,
                "top_right": top_right,
                "bottom_right": bottom_right,
                "bottom_left": bottom_left,
            },
        )
        return result if isinstance(result, str) else str(result)

    # -- control ----------------------------------------------------------

    def render_all(self) -> str:
        """Trigger a full render of the document.

        Returns:
            Server status string.
        """
        result = self.call_tool("render_all")
        return result if isinstance(result, str) else str(result)

    def wait_for_render(self, timeout: float = 120.0, poll_interval: float = 0.5) -> bool:
        """Poll until the document finishes rendering.

        The server may not flip ``rendering=True`` immediately after
        :meth:`render_all`, so this method waits 0.5 s before starting,
        then handles two scenarios:

        - Render started and finished: detected by a ``True → False``
          transition in ``get_render_status``.
        - Render already finished before polling began: detected by
          four consecutive ``False`` readings without ever seeing ``True``.

        Args:
            timeout: Maximum seconds to wait.
            poll_interval: Seconds between status checks.

        Returns:
            ``True`` when rendering is done. Returns ``True`` even on timeout
            (the app continues rendering in the background regardless).
        """
        # Give the render thread time to set its flag before we start polling
        time.sleep(0.5)
        deadline = time.monotonic() + timeout
        was_rendering = False
        not_rendering_count = 0
        while time.monotonic() < deadline:
            status = self.get_render_status()
            if status.rendering:
                was_rendering = True
                not_rendering_count = 0
            else:
                not_rendering_count += 1
                if was_rendering:
                    # Transitioned rendering → done
                    time.sleep(0.5)
                    return True
                if not_rendering_count >= 4:
                    # Render completed before we started polling
                    time.sleep(0.5)
                    return True
            time.sleep(poll_interval)
        return True

    def get_render_status(self) -> RenderStatus:
        """Check whether the document is currently rendering.

        Returns:
            :class:`~vexy_lines_api.types.RenderStatus` with current state.
        """
        data = self.call_tool("get_render_status")
        if isinstance(data, str):
            msg = f"Unexpected response from get_render_status: {data}"
            raise MCPError(msg)
        return RenderStatus(rendering=bool(data.get("rendering", False)))

    # -- high-level export API --------------------------------------------

    def render(self, timeout: float = 120.0) -> bool:
        """Render all layers and wait for completion.

        Combines :meth:`render_all` + :meth:`wait_for_render` into a single call.

        Args:
            timeout: Maximum wait time in seconds.

        Returns:
            ``True`` if render completed, ``False`` if timed out.
        """
        self.render_all()
        return self.wait_for_render(timeout=timeout)

    def export_svg(self, path: str, *, dpi: int | None = None) -> Path:
        """Export the document as SVG.

        Args:
            path: Output file path (``.svg`` extension recommended).
            dpi: Override document DPI for export.

        Returns:
            Resolved absolute path of the exported file.
        """
        resolved = Path(path).expanduser().resolve()
        self.call_tool("export_document", self._export_args(str(resolved), "svg", dpi))
        return resolved

    def export_pdf(self, path: str, *, dpi: int | None = None) -> Path:
        """Export the document as PDF.

        Args:
            path: Output file path (``.pdf`` extension recommended).
            dpi: Override document DPI for export.

        Returns:
            Resolved absolute path of the exported file.
        """
        resolved = Path(path).expanduser().resolve()
        self.call_tool("export_document", self._export_args(str(resolved), "pdf", dpi))
        return resolved

    def export_png(self, path: str, *, dpi: int | None = None) -> Path:
        """Export the document as PNG (raster).

        Args:
            path: Output file path (``.png`` extension recommended).
            dpi: Override document DPI for export. Lower values export faster.

        Returns:
            Resolved absolute path of the exported file.
        """
        resolved = Path(path).expanduser().resolve()
        self.call_tool("export_document", self._export_args(str(resolved), "png", dpi))
        return resolved

    def export_jpeg(self, path: str, *, dpi: int | None = None) -> Path:
        """Export the document as JPEG (raster).

        Args:
            path: Output file path (``.jpg`` or ``.jpeg`` extension recommended).
            dpi: Override document DPI for export. Lower values export faster.

        Returns:
            Resolved absolute path of the exported file.
        """
        resolved = Path(path).expanduser().resolve()
        self.call_tool("export_document", self._export_args(str(resolved), "jpg", dpi))
        return resolved

    def export_eps(self, path: str, *, dpi: int | None = None) -> Path:
        """Export the document as EPS (Encapsulated PostScript).

        Args:
            path: Output file path (``.eps`` extension recommended).
            dpi: Override document DPI for export.

        Returns:
            Resolved absolute path of the exported file.
        """
        resolved = Path(path).expanduser().resolve()
        self.call_tool("export_document", self._export_args(str(resolved), "eps", dpi))
        return resolved

    def svg(self) -> str:
        """Export the document as SVG and return the SVG content as a string.

        Exports to a temporary file, reads it, then cleans up.
        Useful for piping SVG into other tools or embedding in web pages.

        Returns:
            SVG content as a string.
        """
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            tmp_path = Path(f.name)
        try:
            self.export_svg(str(tmp_path))
            return tmp_path.read_text(encoding="utf-8")
        finally:
            tmp_path.unlink(missing_ok=True)

    def svg_parsed(self) -> object:
        """Export the document as SVG and return a parsed svglab ``Svg`` object.

        Provides full SVG manipulation: element traversal, attribute editing,
        bounding box calculation, and rendering to raster images.

        Requires::

            pip install vexy-lines-apy[svg]

        Returns:
            A ``svglab.Svg`` object (from the svglab package).

        Raises:
            ImportError: If svglab is not installed.
        """
        try:
            from svglab import parse_svg  # type: ignore[import-untyped]
        except ImportError:
            msg = "'svglab' is required for SVG parsing. Install with: pip install vexy-lines-apy[svg]"
            raise ImportError(msg) from None
        svg_string = self.svg()
        return parse_svg(svg_string)

    def _export_args(self, path: str, fmt: str, dpi: int | None) -> dict[str, object]:
        """Build arguments dict for ``export_document`` tool call."""
        args: dict[str, object] = {"path": path, "format": fmt}
        if dpi is not None:
            args["dpi"] = dpi
        return args

    def undo(self) -> str:
        """Undo the last action.

        Returns:
            Server status string.
        """
        result = self.call_tool("undo")
        return result if isinstance(result, str) else str(result)

    def redo(self) -> str:
        """Redo the last undone action.

        Returns:
            Server status string.
        """
        result = self.call_tool("redo")
        return result if isinstance(result, str) else str(result)

    def get_selection(self) -> dict[str, object] | str:
        """Get the currently selected object(s).

        Returns:
            Selection data as a dict or status string.
        """
        return self.call_tool("get_selection")

    def select_object(self, object_id: int) -> str:
        """Select an object by ID.

        Args:
            object_id: Object to select.

        Returns:
            Server status string.
        """
        result = self.call_tool("select_object", {"id": object_id})
        return result if isinstance(result, str) else str(result)
