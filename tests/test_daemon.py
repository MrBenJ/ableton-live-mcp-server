"""
Unit tests for AbletonOSCDaemon logic.
Focuses on the asyncio future queue (FIFO ordering, concurrent requests,
timeout cleanup) and handle_ableton_message behaviour.
No real OSC or TCP sockets are opened.
"""
import asyncio
import pytest
from unittest.mock import MagicMock, patch

from osc_daemon import AbletonOSCDaemon


@pytest.fixture
def daemon():
    """A daemon instance with OSC client mocked out so no UDP socket is opened."""
    with patch("osc_daemon.SimpleUDPClient"):
        d = AbletonOSCDaemon()
    return d


# ---------------------------------------------------------------------------
# handle_ableton_message — basic resolution
# ---------------------------------------------------------------------------

class TestHandleAbletonMessage:
    async def test_resolves_pending_future(self, daemon):
        future = asyncio.get_running_loop().create_future()
        daemon.pending_responses['/live/song/get/tempo'] = [future]

        daemon.handle_ableton_message('/live/song/get/tempo', 128.0)

        result = await future
        assert result['status'] == 'success'
        assert result['data'] == (128.0,)
        assert result['address'] == '/live/song/get/tempo'

    async def test_cleans_up_address_after_last_future(self, daemon):
        future = asyncio.get_running_loop().create_future()
        daemon.pending_responses['/live/song/get/tempo'] = [future]

        daemon.handle_ableton_message('/live/song/get/tempo', 128.0)
        await future

        assert '/live/song/get/tempo' not in daemon.pending_responses

    async def test_no_pending_future_is_harmless(self, daemon):
        """Receiving an OSC message with no pending listener should not raise."""
        daemon.handle_ableton_message('/live/some/address', 'data')
        # No exception means pass

    async def test_already_done_future_is_skipped(self, daemon):
        """If a future was cancelled (e.g. timed out), handle_ableton_message must not crash."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.cancel()
        daemon.pending_responses['/live/song/get/tempo'] = [future]

        daemon.handle_ableton_message('/live/song/get/tempo', 99.0)
        # The list should be cleaned up even though the future was done
        assert '/live/song/get/tempo' not in daemon.pending_responses


# ---------------------------------------------------------------------------
# FIFO ordering — concurrent requests to the same address
# ---------------------------------------------------------------------------

class TestFIFOOrdering:
    async def test_two_requests_resolved_in_order(self, daemon):
        loop = asyncio.get_running_loop()
        future1 = loop.create_future()
        future2 = loop.create_future()
        daemon.pending_responses['/live/song/get/tempo'] = [future1, future2]

        # First response should resolve future1
        daemon.handle_ableton_message('/live/song/get/tempo', 120.0)
        # Second response should resolve future2
        daemon.handle_ableton_message('/live/song/get/tempo', 130.0)

        result1 = await future1
        result2 = await future2
        assert result1['data'] == (120.0,)
        assert result2['data'] == (130.0,)

    async def test_address_cleaned_up_after_all_futures_resolved(self, daemon):
        loop = asyncio.get_running_loop()
        f1 = loop.create_future()
        f2 = loop.create_future()
        daemon.pending_responses['/live/clip/get/length'] = [f1, f2]

        daemon.handle_ableton_message('/live/clip/get/length', 4.0)
        assert '/live/clip/get/length' in daemon.pending_responses  # f2 still waiting

        daemon.handle_ableton_message('/live/clip/get/length', 8.0)
        assert '/live/clip/get/length' not in daemon.pending_responses  # all done

    async def test_different_addresses_are_independent(self, daemon):
        loop = asyncio.get_running_loop()
        tempo_future = loop.create_future()
        name_future = loop.create_future()
        daemon.pending_responses['/live/song/get/tempo'] = [tempo_future]
        daemon.pending_responses['/live/track/get/name'] = [name_future]

        daemon.handle_ableton_message('/live/song/get/tempo', 140.0)
        daemon.handle_ableton_message('/live/track/get/name', 'Bass')

        assert (await tempo_future)['data'] == (140.0,)
        assert (await name_future)['data'] == ('Bass',)
        assert not daemon.pending_responses


# ---------------------------------------------------------------------------
# Timeout cleanup
# ---------------------------------------------------------------------------

class TestTimeoutCleanup:
    async def test_stale_future_removed_on_timeout(self, daemon):
        """
        Simulate what happens when wait_for times out:
        the future is cancelled, then we remove it from pending_responses.
        """
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        address = '/live/song/get/tempo'
        daemon.pending_responses[address] = [future]

        # Simulate wait_for cancelling the future on timeout
        future.cancel()

        # Simulate the cleanup logic in handle_socket_client
        if address in daemon.pending_responses:
            try:
                daemon.pending_responses[address].remove(future)
            except ValueError:
                pass
            if not daemon.pending_responses[address]:
                del daemon.pending_responses[address]

        assert address not in daemon.pending_responses

    async def test_late_response_after_timeout_does_not_raise(self, daemon):
        """
        If Ableton sends a response after the client already timed out and
        cleaned up, handle_ableton_message should be a no-op (no address in dict).
        """
        # Nothing in pending_responses — simulates post-timeout state
        daemon.handle_ableton_message('/live/song/get/tempo', 120.0)
        # Should not raise


# ---------------------------------------------------------------------------
# pending_responses structure
# ---------------------------------------------------------------------------

class TestPendingResponsesStructure:
    def test_initial_state_is_empty(self, daemon):
        assert daemon.pending_responses == {}

    async def test_multiple_addresses_stored_independently(self, daemon):
        loop = asyncio.get_running_loop()
        f1 = loop.create_future()
        f2 = loop.create_future()

        daemon.pending_responses['/live/song/get/tempo'] = [f1]
        daemon.pending_responses['/live/clip/get/name'] = [f2]

        assert len(daemon.pending_responses) == 2
        assert daemon.pending_responses['/live/song/get/tempo'] is not \
               daemon.pending_responses['/live/clip/get/name']
