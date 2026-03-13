"""
Tests for pure helper functions:
  - midi_to_note_name
  - strip_osc_prefix
  - _fetch_all_scenes (async, uses mocked send_command)
"""
import pytest
from unittest.mock import AsyncMock, patch

from mcp_ableton_server import midi_to_note_name, strip_osc_prefix, _fetch_all_scenes


# ---------------------------------------------------------------------------
# midi_to_note_name
# ---------------------------------------------------------------------------

class TestMidiToNoteName:
    def test_middle_c(self):
        assert midi_to_note_name(60) == "C4"

    def test_a4_concert_pitch(self):
        assert midi_to_note_name(69) == "A4"

    def test_lowest_midi_note(self):
        assert midi_to_note_name(0) == "C-1"

    def test_highest_midi_note(self):
        assert midi_to_note_name(127) == "G9"

    def test_flat_preference(self):
        # Should prefer flats (Db not C#, Eb not D#, etc.)
        assert midi_to_note_name(61) == "Db4"
        assert midi_to_note_name(63) == "Eb4"
        assert midi_to_note_name(66) == "Gb4"
        assert midi_to_note_name(68) == "Ab4"
        assert midi_to_note_name(70) == "Bb4"

    def test_float_pitch_is_handled(self):
        # OSC often sends floats; int() coercion must work
        assert midi_to_note_name(60.0) == "C4"


# ---------------------------------------------------------------------------
# strip_osc_prefix
# ---------------------------------------------------------------------------

class TestStripOscPrefix:
    def test_single_prefix_stripped(self):
        data = [2, "hello", "world"]
        assert strip_osc_prefix(data, 2) == ["hello", "world"]

    def test_two_prefix_values_stripped(self):
        data = [1, 3, "note_data"]
        assert strip_osc_prefix(data, 1, 3) == ["note_data"]

    def test_prefix_mismatch_returns_original(self):
        data = [5, "hello"]
        assert strip_osc_prefix(data, 99) == [5, "hello"]

    def test_float_int_mismatch_still_strips(self):
        # AbletonOSC sends track/clip indices as floats; int() comparison must match
        data = [2.0, 0.0, "clip_name"]
        assert strip_osc_prefix(data, 2, 0) == ["clip_name"]

    def test_empty_prefix_returns_original(self):
        data = [1, 2, 3]
        assert strip_osc_prefix(data) == [1, 2, 3]

    def test_data_shorter_than_prefix_returns_original(self):
        data = [1]
        assert strip_osc_prefix(data, 1, 2) == [1]

    def test_all_data_is_prefix_returns_empty(self):
        data = [0, 1]
        assert strip_osc_prefix(data, 0, 1) == []


# ---------------------------------------------------------------------------
# _fetch_all_scenes
# ---------------------------------------------------------------------------

class TestFetchAllScenes:
    async def test_returns_scene_list(self):
        """Normal case: num_scenes returns 3, each scene name is fetched."""
        def side_effect(address, args):
            if address == '/live/song/get/num_scenes':
                return {'status': 'success', 'data': (3,)}
            if address == '/live/scene/get/name':
                scene_idx = args[0]
                names = {0: 'INTRO', 1: 'DROP', 2: 'BREAK'}
                return {'status': 'success', 'data': (scene_idx, names[scene_idx])}
            return {'status': 'error'}

        mock = AsyncMock(side_effect=side_effect)
        with patch("mcp_ableton_server.ableton_client.send_command", mock):
            result = await _fetch_all_scenes()

        assert result == [(0, 'INTRO'), (1, 'DROP'), (2, 'BREAK')]

    async def test_stops_on_failed_scene_fetch(self):
        """If a scene name fetch fails, iteration stops (scenes are contiguous)."""
        def side_effect(address, args):
            if address == '/live/song/get/num_scenes':
                return {'status': 'success', 'data': (5,)}
            if address == '/live/scene/get/name':
                scene_idx = args[0]
                if scene_idx < 2:
                    return {'status': 'success', 'data': (scene_idx, f'Scene{scene_idx}')}
                return {'status': 'error', 'message': 'Out of range'}
            return {'status': 'error'}

        mock = AsyncMock(side_effect=side_effect)
        with patch("mcp_ableton_server.ableton_client.send_command", mock):
            result = await _fetch_all_scenes()

        assert result == [(0, 'Scene0'), (1, 'Scene1')]

    async def test_fallback_when_num_scenes_fails(self):
        """If num_scenes endpoint errors, it falls back to 16 and fetches until failure."""
        call_count = 0

        def side_effect(address, args):
            nonlocal call_count
            if address == '/live/song/get/num_scenes':
                return {'status': 'error'}
            if address == '/live/scene/get/name':
                call_count += 1
                if call_count <= 3:
                    return {'status': 'success', 'data': (args[0], f'S{args[0]}')}
                return {'status': 'error'}
            return {'status': 'error'}

        mock = AsyncMock(side_effect=side_effect)
        with patch("mcp_ableton_server.ableton_client.send_command", mock):
            result = await _fetch_all_scenes()

        assert len(result) == 3
