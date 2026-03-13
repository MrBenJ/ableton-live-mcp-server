"""
Shared fixtures for the ableton-live-mcp-server test suite.
All tests are pure unit tests — no Ableton connection required.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_send_command():
    """
    Patch ableton_client.send_command with an AsyncMock for the duration of a test.
    Usage:
        async def test_something(mock_send_command):
            mock_send_command.return_value = {'status': 'success', 'data': (42.0,)}
    """
    with patch(
        "mcp_ableton_server.ableton_client.send_command",
        new_callable=AsyncMock,
    ) as mock:
        yield mock
