"""
Unit tests for AbletonClient TCP framing.

Covers:
  - _recv_all: exact reads, fragmented TCP delivery, connection-closed detection
  - _send_recv: length-prefixed send, length-prefixed receive, large payloads
               that would have been silently truncated by the old recv(4096),
               and fragmented receive paths
"""
import json
import struct
import pytest
from unittest.mock import MagicMock, patch, call

from mcp_ableton_server import AbletonClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """AbletonClient with a mocked socket — no real TCP connection opened."""
    c = AbletonClient()
    c.sock = MagicMock()
    c.connected = True
    return c


def frame(data: dict) -> bytes:
    """Encode a dict as a length-prefixed JSON message (matching the wire protocol)."""
    payload = json.dumps(data).encode()
    return struct.pack('>I', len(payload)) + payload


def fragmented_recv(data: bytes, chunk_size: int):
    """
    Return a side_effect callable that simulates fragmented TCP delivery.
    Each call to recv(n) returns at most min(chunk_size, n) bytes from data,
    exactly as a real TCP socket would — never returning more than requested.
    """
    pos = 0

    def _recv(n):
        nonlocal pos
        to_read = min(chunk_size, n, len(data) - pos)
        chunk = data[pos:pos + to_read]
        pos += to_read
        return chunk

    return _recv


# ---------------------------------------------------------------------------
# _recv_all
# ---------------------------------------------------------------------------

class TestRecvAll:
    def test_reads_exact_bytes_single_chunk(self, client):
        client.sock.recv.return_value = b'hello'
        assert client._recv_all(5) == b'hello'
        client.sock.recv.assert_called_once_with(5)

    def test_reads_fragmented_delivery(self, client):
        """TCP may split a message across multiple recv() calls."""
        client.sock.recv.side_effect = [b'he', b'llo']
        assert client._recv_all(5) == b'hello'
        assert client.sock.recv.call_count == 2

    def test_reads_many_small_fragments(self, client):
        client.sock.recv.side_effect = [bytes([b]) for b in b'abcdef']
        assert client._recv_all(6) == b'abcdef'

    def test_raises_connection_error_on_empty_recv(self, client):
        """Empty recv() means the remote end closed the connection."""
        client.sock.recv.return_value = b''
        with pytest.raises(ConnectionError):
            client._recv_all(4)

    def test_raises_if_connection_closes_mid_read(self, client):
        """Connection closes after partial data — must still raise."""
        client.sock.recv.side_effect = [b'ab', b'']
        with pytest.raises(ConnectionError):
            client._recv_all(4)

    def test_asks_for_remaining_bytes_each_iteration(self, client):
        """recv() should be called with decreasing byte counts as data accumulates."""
        client.sock.recv.side_effect = [b'xx', b'yy', b'z']
        client._recv_all(5)
        calls = client.sock.recv.call_args_list
        assert calls[0] == call(5)
        assert calls[1] == call(3)  # 5 - 2 remaining
        assert calls[2] == call(1)  # 5 - 4 remaining


# ---------------------------------------------------------------------------
# _send_recv — length-prefixed protocol
# ---------------------------------------------------------------------------

class TestSendRecv:
    def _setup_recv(self, client, response: dict, chunk_size: int = None):
        """
        Configure sock.recv side_effect to return a length-prefixed response,
        optionally fragmented into chunk_size pieces using a stateful callable
        that respects the n argument (just like a real TCP socket would).
        """
        raw = frame(response)
        if chunk_size:
            client.sock.recv.side_effect = fragmented_recv(raw, chunk_size)
        else:
            # Return length header then payload in two calls
            client.sock.recv.side_effect = [raw[:4], raw[4:]]

    def test_sends_length_prefixed_message(self, client):
        self._setup_recv(client, {'status': 'sent'})
        client._send_recv({'command': 'send_message', 'address': '/test', 'args': []})

        sent = client.sock.sendall.call_args[0][0]
        msg_len = struct.unpack('>I', sent[:4])[0]
        parsed = json.loads(sent[4:4 + msg_len].decode())
        assert parsed['command'] == 'send_message'
        assert parsed['address'] == '/test'

    def test_receives_length_prefixed_response(self, client):
        # JSON always deserializes arrays as lists, never tuples — use lists in assertions
        expected = {'status': 'success', 'data': [128.0]}
        self._setup_recv(client, expected)
        result = client._send_recv({'command': 'send_message', 'address': '/test', 'args': []})
        assert result == expected

    def test_large_payload_received_correctly(self, client):
        """
        Payload larger than the old recv(4096) limit must be reassembled in full.
        This is the core regression test for the truncation bug.
        Using string values guarantees the payload is large enough.
        """
        big_response = {'status': 'success', 'data': ['note_data_item'] * 400}
        payload = json.dumps(big_response).encode()
        assert len(payload) > 4096, "Test payload must exceed the old buffer size"

        self._setup_recv(client, big_response)
        result = client._send_recv({'command': 'send_message', 'address': '/test', 'args': []})
        assert result['status'] == 'success'
        assert len(result['data']) == 400

    def test_fragmented_large_payload_reassembled(self, client):
        """
        Even when TCP delivers data in 512-byte chunks, the full message arrives.
        The stateful fragmented_recv() callable respects recv(n) so _recv_all
        loops correctly without over-reading.
        """
        big_response = {'status': 'success', 'data': ['note_data_item'] * 400}
        self._setup_recv(client, big_response, chunk_size=512)
        result = client._send_recv({'command': 'send_message', 'address': '/test', 'args': []})
        assert result['status'] == 'success'
        assert len(result['data']) == 400

    def test_marks_disconnected_on_socket_error(self, client):
        client.sock.sendall.side_effect = OSError('Broken pipe')
        result = client._send_recv({'command': 'send_message', 'address': '/test', 'args': []})
        assert result['status'] == 'error'
        assert client.connected is False

    def test_marks_disconnected_on_connection_closed_during_recv(self, client):
        """Connection drops after send — empty recv triggers ConnectionError."""
        client.sock.recv.return_value = b''
        result = client._send_recv({'command': 'send_message', 'address': '/test', 'args': []})
        assert result['status'] == 'error'
        assert client.connected is False

    def test_returns_error_when_not_connected(self, client):
        client.connected = False
        client.sock = None
        with patch.object(client, '_ensure_connected', return_value=False):
            result = client._send_recv({'command': 'test'})
        assert result['status'] == 'error'
        assert 'Not connected' in result['message']

    def test_full_roundtrip_encoding(self, client):
        """Verify the exact bytes on the wire match what the daemon expects."""
        # JSON arrays always deserialize to lists — use list here
        response = {'status': 'success', 'data': ['Track A', 'Track B']}
        self._setup_recv(client, response)

        msg = {'command': 'send_message', 'address': '/live/song/get/track_names', 'args': []}
        result = client._send_recv(msg)

        # Check outgoing wire format
        sent = client.sock.sendall.call_args[0][0]
        length = struct.unpack('>I', sent[:4])[0]
        assert sent[4:4 + length] == json.dumps(msg).encode()

        # Check incoming parsing
        assert result == response
