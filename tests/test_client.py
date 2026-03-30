# this_file: vexy-lines-apy/tests/test_client.py
"""Tests for vexy_lines_api.client module.

All tests mock the TCP socket to avoid requiring a running Vexy Lines instance.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from vexy_lines_api.client import APP_NAME, MCP_PORT, PROTOCOL_VERSION, MCPClient, MCPError
from vexy_lines_api.types import DocumentInfo, LayerNode, NewDocumentResult, RenderStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _jsonrpc_response(result: dict | str, request_id: int = 1) -> bytes:
    """Build a newline-delimited JSON-RPC success response."""
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}, separators=(",", ":")).encode() + b"\n"


def _jsonrpc_error(code: int, message: str, request_id: int = 1) -> bytes:
    """Build a newline-delimited JSON-RPC error response."""
    return (
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}, separators=(",", ":")
        ).encode()
        + b"\n"
    )


def _tool_response(data: dict | str, request_id: int = 1) -> bytes:
    """Build a tool/call response wrapping data in content[0].text."""
    text = json.dumps(data) if isinstance(data, dict) else data
    result = {"content": [{"text": text}]}
    return _jsonrpc_response(result, request_id)


def _make_handshake_response() -> bytes:
    """Build the initialize response for the MCP handshake."""
    return _jsonrpc_response({"protocolVersion": PROTOCOL_VERSION}, request_id=1)


class MockSocket:
    """A mock socket that returns pre-configured responses in order."""

    def __init__(self, responses: list[bytes]) -> None:
        self._responses = list(responses)
        self._sent: list[bytes] = []

    def connect(self, addr: tuple[str, int]) -> None:
        pass

    def settimeout(self, timeout: float) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self._sent.append(data)

    def recv(self, bufsize: int) -> bytes:
        if not self._responses:
            return b""
        return self._responses.pop(0)

    def shutdown(self, how: int) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# MCPError tests
# ---------------------------------------------------------------------------


class TestMCPError:
    """Tests for the MCPError exception class."""

    def test_message_attribute(self):
        err = MCPError("test error")
        assert err.message == "test error"
        assert str(err) == "test error"

    def test_inheritance(self):
        assert issubclass(MCPError, Exception)

    def test_raise_and_catch(self):
        with pytest.raises(MCPError, match="connection failed"):
            msg = "connection failed"
            raise MCPError(msg)


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


class TestConnectionFailure:
    """Tests for connection failure handling."""

    def test_connection_refused_no_auto_launch(self):
        """When auto_launch=False, connection failure raises MCPError immediately."""
        client = MCPClient(auto_launch=False)
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = OSError("Connection refused")
            mock_sock_cls.return_value = mock_sock
            with pytest.raises(MCPError, match="Cannot connect"):
                client.__enter__()

    def test_connection_refused_with_auto_launch_unsupported_platform(self):
        """On unsupported platforms, auto-launch raises MCPError."""
        client = MCPClient(auto_launch=True)
        with (
            patch("socket.socket") as mock_sock_cls,
            patch("sys.platform", "freebsd"),
        ):
            mock_sock = MagicMock()
            mock_sock.connect.side_effect = OSError("Connection refused")
            mock_sock_cls.return_value = mock_sock
            with pytest.raises(MCPError, match="Auto-launch not supported"):
                client.__enter__()


class TestAutoLaunchMacOS:
    """Tests for macOS auto-launch logic."""

    def test_launch_app_darwin(self):
        """On macOS, _launch_app calls 'open -a Vexy Lines'."""
        client = MCPClient()
        with (
            patch("sys.platform", "darwin"),
            patch("subprocess.run") as mock_run,
        ):
            client._launch_app()
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert args[0][0] == ["open", "-a", APP_NAME]


class TestAutoLaunchWindows:
    """Tests for Windows auto-launch logic."""

    def test_launch_app_win32_not_found(self):
        """On Windows, raises MCPError when exe not found."""
        client = MCPClient()
        with (
            patch("sys.platform", "win32"),
            patch("pathlib.Path.exists", return_value=False),
            pytest.raises(MCPError, match="not found"),
        ):
            client._launch_app()

    def test_launch_app_win32_found(self):
        """On Windows, launches the found exe."""
        client = MCPClient()
        with (
            patch("sys.platform", "win32"),
            patch("pathlib.Path.exists", side_effect=lambda: True),
            patch("subprocess.Popen") as mock_popen,
        ):
            # Make only the first candidate exist
            with patch("pathlib.Path.exists", return_value=True):
                client._launch_app()
            mock_popen.assert_called_once()


# ---------------------------------------------------------------------------
# Handshake tests
# ---------------------------------------------------------------------------


class TestHandshake:
    """Tests for the MCP initialize/initialized handshake."""

    def test_handshake_success(self):
        """Successful handshake with matching protocol version."""
        mock_sock = MockSocket([_make_handshake_response()])
        client = MCPClient(auto_launch=False)
        with patch("socket.socket", return_value=mock_sock):
            ctx = client.__enter__()
            assert ctx is client
            client.__exit__(None, None, None)

    def test_handshake_protocol_mismatch(self):
        """Protocol version mismatch raises MCPError."""
        bad_response = _jsonrpc_response({"protocolVersion": "9999-01-01"}, request_id=1)
        mock_sock = MockSocket([bad_response])
        client = MCPClient(auto_launch=False)
        with patch("socket.socket", return_value=mock_sock), pytest.raises(MCPError, match="Protocol mismatch"):
            client.__enter__()

    def test_handshake_sends_correct_client_info(self):
        """Handshake sends vexy-lines-apy as client name."""
        mock_sock = MockSocket([_make_handshake_response()])
        client = MCPClient(auto_launch=False)
        with patch("socket.socket", return_value=mock_sock):
            client.__enter__()
            # Parse the first sent message (initialize request)
            sent_data = json.loads(mock_sock._sent[0].decode())
            assert sent_data["method"] == "initialize"
            assert sent_data["params"]["clientInfo"]["name"] == "vexy-lines-apy"
            assert sent_data["params"]["protocolVersion"] == PROTOCOL_VERSION
            client.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# call_tool / JSON-RPC tests
# ---------------------------------------------------------------------------


class TestCallTool:
    """Tests for the call_tool method and JSON-RPC message format."""

    def _make_connected_client(self, responses: list[bytes]) -> tuple[MCPClient, MockSocket]:
        """Create a client that has completed the handshake."""
        all_responses = [_make_handshake_response(), *responses]
        mock_sock = MockSocket(all_responses)
        client = MCPClient(auto_launch=False)
        with patch("socket.socket", return_value=mock_sock):
            client.__enter__()
        return client, mock_sock

    def test_call_tool_json_response(self):
        """call_tool parses JSON text content into a dict."""
        tool_resp = _tool_response({"width_mm": 210.0, "height_mm": 297.0}, request_id=2)
        client, _sock = self._make_connected_client([tool_resp])
        result = client.call_tool("get_document_info")
        assert isinstance(result, dict)
        assert result["width_mm"] == 210.0

    def test_call_tool_string_response(self):
        """call_tool returns raw string when text is not JSON."""
        text = "Document saved successfully"
        resp = _tool_response(text, request_id=2)
        client, _sock = self._make_connected_client([resp])
        result = client.call_tool("save_document")
        assert result == text

    def test_call_tool_sends_correct_format(self):
        """Verify the JSON-RPC message structure sent to the server."""
        tool_resp = _tool_response({"status": "ok"}, request_id=2)
        client, sock = self._make_connected_client([tool_resp])
        client.call_tool("new_document", {"dpi": 300})
        # The tool call is the 3rd message sent (after initialize request + initialized notification)
        sent = json.loads(sock._sent[2].decode())
        assert sent["jsonrpc"] == "2.0"
        assert sent["method"] == "tools/call"
        assert sent["params"]["name"] == "new_document"
        assert sent["params"]["arguments"]["dpi"] == 300

    def test_server_error_raises_mcp_error(self):
        """Server error response raises MCPError with code and message."""
        error_resp = _jsonrpc_error(-32600, "Invalid request", request_id=2)
        client, _sock = self._make_connected_client([error_resp])
        with pytest.raises(MCPError, match="MCP error -32600: Invalid request"):
            client.call_tool("bad_tool")

    def test_connection_closed_raises_mcp_error(self):
        """Empty recv (connection closed) raises MCPError."""
        client, _sock = self._make_connected_client([])
        # Socket returns empty bytes = connection closed
        with pytest.raises(MCPError, match="Connection closed"):
            client.call_tool("anything")

    def test_invalid_json_raises_mcp_error(self):
        """Invalid JSON from server raises MCPError."""
        client, _sock = self._make_connected_client([b"not-json\n"])
        with pytest.raises(MCPError, match="Invalid JSON"):
            client.call_tool("anything")


# ---------------------------------------------------------------------------
# Typed method tests
# ---------------------------------------------------------------------------


class TestTypedMethods:
    """Tests for typed wrapper methods (get_document_info, etc.)."""

    def _make_connected_client(self, responses: list[bytes]) -> MCPClient:
        all_responses = [_make_handshake_response(), *responses]
        mock_sock = MockSocket(all_responses)
        client = MCPClient(auto_launch=False)
        with patch("socket.socket", return_value=mock_sock):
            client.__enter__()
        return client

    def test_get_document_info(self):
        resp = _tool_response(
            {"width_mm": 210.0, "height_mm": 297.0, "resolution": 300.0, "units": "mm", "has_changes": True},
            request_id=2,
        )
        client = self._make_connected_client([resp])
        info = client.get_document_info()
        assert isinstance(info, DocumentInfo)
        assert info.width_mm == 210.0
        assert info.has_changes is True

    def test_new_document(self):
        resp = _tool_response(
            {"status": "ok", "width": 1920.0, "height": 1080.0, "dpi": 300.0, "root_id": 42},
            request_id=2,
        )
        client = self._make_connected_client([resp])
        result = client.new_document(width=1920, height=1080, dpi=300)
        assert isinstance(result, NewDocumentResult)
        assert result.root_id == 42
        assert result.status == "ok"

    def test_get_layer_tree(self):
        tree = {
            "id": 1,
            "type": "document",
            "caption": "Root",
            "visible": True,
            "children": [
                {"id": 2, "type": "group", "caption": "Group 1", "visible": True},
            ],
        }
        resp = _tool_response(tree, request_id=2)
        client = self._make_connected_client([resp])
        result = client.get_layer_tree()
        assert isinstance(result, LayerNode)
        assert result.id == 1
        assert len(result.children) == 1

    def test_get_render_status(self):
        resp = _tool_response({"rendering": True}, request_id=2)
        client = self._make_connected_client([resp])
        status = client.get_render_status()
        assert isinstance(status, RenderStatus)
        assert status.rendering is True

    def test_add_group(self):
        resp = _tool_response({"id": 10, "status": "ok"}, request_id=2)
        client = self._make_connected_client([resp])
        result = client.add_group(parent_id=1, caption="New Group")
        assert result["id"] == 10

    def test_add_layer(self):
        resp = _tool_response({"id": 11, "status": "ok"}, request_id=2)
        client = self._make_connected_client([resp])
        result = client.add_layer(group_id=10)
        assert result["id"] == 11

    def test_add_fill(self):
        resp = _tool_response({"id": 12, "status": "ok"}, request_id=2)
        client = self._make_connected_client([resp])
        result = client.add_fill(layer_id=11, fill_type="linear", color="#ff0000")
        assert result["id"] == 12


# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_app_name(self):
        assert APP_NAME == "Vexy Lines"

    def test_mcp_port(self):
        assert MCP_PORT == 47384

    def test_protocol_version(self):
        assert PROTOCOL_VERSION == "2024-11-05"


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------


class TestContextManager:
    """Tests for the context manager protocol."""

    def test_exit_closes_socket(self):
        """__exit__ calls _close to clean up the socket."""
        mock_sock = MockSocket([_make_handshake_response()])
        client = MCPClient(auto_launch=False)
        with patch("socket.socket", return_value=mock_sock):
            client.__enter__()
            assert client._sock is not None
            client.__exit__(None, None, None)
            assert client._sock is None

    def test_close_idempotent(self):
        """Calling _close when already closed does not error."""
        client = MCPClient(auto_launch=False)
        client._sock = None
        client._close()  # Should not raise


# ---------------------------------------------------------------------------
# Transport tests
# ---------------------------------------------------------------------------


class TestTransport:
    """Tests for low-level transport methods."""

    def test_send_bytes_not_connected(self):
        """Sending on a disconnected client raises MCPError."""
        client = MCPClient(auto_launch=False)
        client._sock = None
        with pytest.raises(MCPError, match="Not connected"):
            client._send_bytes({"test": True})

    def test_recv_response_not_connected(self):
        """Receiving on a disconnected client raises MCPError."""
        client = MCPClient(auto_launch=False)
        client._sock = None
        with pytest.raises(MCPError, match="Not connected"):
            client._recv_response()

    def test_next_id_increments(self):
        """Request IDs increment monotonically."""
        client = MCPClient()
        assert client._next_id() == 1
        assert client._next_id() == 2
        assert client._next_id() == 3
