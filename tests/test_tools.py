"""
Unit tests for all @mcp.tool() functions in mcp_ableton_server.py.
ableton_client.send_command is mocked so no Ableton connection is needed.
"""
import pytest
from unittest.mock import AsyncMock, patch, call

import mcp_ableton_server as server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_success(data=()):
    return {'status': 'success', 'data': data}

def make_error(msg='Something went wrong'):
    return {'status': 'error', 'message': msg}

def make_sent():
    return {'status': 'sent'}


# ---------------------------------------------------------------------------
# get_track_names
# ---------------------------------------------------------------------------

class TestGetTrackNames:
    async def test_returns_formatted_list(self, mock_send_command):
        mock_send_command.return_value = make_success(('Kick', 'Snare', 'Bass'))
        result = await server.get_track_names()
        assert result == "Track Names: Kick, Snare, Bass"

    async def test_empty_tracks(self, mock_send_command):
        mock_send_command.return_value = make_success(())
        result = await server.get_track_names()
        assert result == "No tracks found"

    async def test_error_response(self, mock_send_command):
        mock_send_command.return_value = make_error('Connection refused')
        result = await server.get_track_names()
        assert "Error" in result
        assert "Connection refused" in result

    async def test_with_index_range(self, mock_send_command):
        mock_send_command.return_value = make_success(('Track A',))
        await server.get_track_names(index_min=0, index_max=1)
        mock_send_command.assert_called_once_with('/live/song/get/track_names', [0, 1])


# ---------------------------------------------------------------------------
# find_track_by_name
# ---------------------------------------------------------------------------

class TestFindTrackByName:
    async def test_finds_exact_match(self, mock_send_command):
        mock_send_command.return_value = make_success(('Kick', 'Snare', 'Bass'))
        result = await server.find_track_by_name('Snare')
        assert 'index 1: Snare' in result

    async def test_case_insensitive(self, mock_send_command):
        mock_send_command.return_value = make_success(('KICK', 'snare', 'Bass'))
        result = await server.find_track_by_name('kick')
        assert 'index 0: KICK' in result

    async def test_partial_match(self, mock_send_command):
        mock_send_command.return_value = make_success(('Bass Guitar', 'Bass Synth', 'Kick'))
        result = await server.find_track_by_name('bass')
        assert 'index 0' in result
        assert 'index 1' in result
        assert 'index 2' not in result

    async def test_no_match(self, mock_send_command):
        mock_send_command.return_value = make_success(('Kick', 'Snare'))
        result = await server.find_track_by_name('Flute')
        assert "No tracks found" in result

    async def test_error_response(self, mock_send_command):
        mock_send_command.return_value = make_error()
        result = await server.find_track_by_name('anything')
        assert "Error" in result


# ---------------------------------------------------------------------------
# get_scene_names
# ---------------------------------------------------------------------------

class TestGetSceneNames:
    async def test_returns_all_scenes(self, mock_send_command):
        def side_effect(address, args):
            if address == '/live/song/get/num_scenes':
                return make_success((2,))
            if address == '/live/scene/get/name':
                names = {0: 'INTRO', 1: 'DROP'}
                return make_success((args[0], names[args[0]]))
        mock_send_command.side_effect = side_effect
        result = await server.get_scene_names()
        assert "INTRO" in result
        assert "DROP" in result
        assert "0" in result
        assert "1" in result

    async def test_no_scenes(self, mock_send_command):
        def side_effect(address, args):
            if address == '/live/song/get/num_scenes':
                return make_success((0,))
            return make_error()
        mock_send_command.side_effect = side_effect
        result = await server.get_scene_names()
        assert "Could not retrieve" in result


# ---------------------------------------------------------------------------
# find_scene_by_name
# ---------------------------------------------------------------------------

class TestFindSceneByName:
    async def test_finds_named_scene(self, mock_send_command):
        def side_effect(address, args):
            if address == '/live/song/get/num_scenes':
                return make_success((3,))
            if address == '/live/scene/get/name':
                names = {0: '', 1: 'DROP', 2: 'BREAK'}
                return make_success((args[0], names[args[0]]))
        mock_send_command.side_effect = side_effect
        result = await server.find_scene_by_name('BREAK')
        assert "index 2" in result

    async def test_case_insensitive(self, mock_send_command):
        def side_effect(address, args):
            if address == '/live/song/get/num_scenes':
                return make_success((2,))
            if address == '/live/scene/get/name':
                return make_success((args[0], 'DROP' if args[0] == 0 else ''))
        mock_send_command.side_effect = side_effect
        result = await server.find_scene_by_name('drop')
        assert "index 0" in result

    async def test_no_match_lists_all_scenes(self, mock_send_command):
        def side_effect(address, args):
            if address == '/live/song/get/num_scenes':
                return make_success((2,))
            if address == '/live/scene/get/name':
                return make_success((args[0], 'INTRO' if args[0] == 0 else 'OUTRO'))
        mock_send_command.side_effect = side_effect
        result = await server.find_scene_by_name('BRIDGE')
        assert "No scenes found" in result
        assert "INTRO" in result
        assert "OUTRO" in result


# ---------------------------------------------------------------------------
# get_clip_info
# ---------------------------------------------------------------------------

class TestGetClipInfo:
    async def test_returns_clip_name_and_length(self, mock_send_command):
        mock_send_command.side_effect = [
            make_success((1, 0, 'My Clip')),   # name response
            make_success((1, 0, 8.0)),          # length response
        ]
        result = await server.get_clip_info(1, 0)
        assert "My Clip" in result
        assert "8" in result

    async def test_no_clip_at_slot(self, mock_send_command):
        mock_send_command.side_effect = [make_error(), make_error()]
        result = await server.get_clip_info(0, 0)
        assert "No clip" in result


# ---------------------------------------------------------------------------
# set_clip_name
# ---------------------------------------------------------------------------

class TestSetClipName:
    async def test_success(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.set_clip_name(0, 0, 'Verse 1')
        assert "Verse 1" in result

    async def test_error(self, mock_send_command):
        mock_send_command.return_value = make_error('Clip not found')
        result = await server.set_clip_name(0, 0, 'Verse 1')
        assert "Error" in result


# ---------------------------------------------------------------------------
# delete_clip
# ---------------------------------------------------------------------------

class TestDeleteClip:
    async def test_success(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.delete_clip(2, 1)
        assert "Deleted" in result

    async def test_error(self, mock_send_command):
        mock_send_command.return_value = make_error()
        result = await server.delete_clip(2, 1)
        assert "Error" in result


# ---------------------------------------------------------------------------
# create_clip
# ---------------------------------------------------------------------------

class TestCreateClip:
    async def test_success(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.create_clip(0, 0, 8.0)
        assert "8.0" in result or "8" in result

    async def test_error(self, mock_send_command):
        mock_send_command.return_value = make_error()
        result = await server.create_clip(0, 0, 4.0)
        assert "Error" in result


# ---------------------------------------------------------------------------
# add_notes_to_clip
# ---------------------------------------------------------------------------

class TestAddNotesToClip:
    async def test_success(self, mock_send_command):
        # First call: length check succeeds; second call: add/notes succeeds
        mock_send_command.side_effect = [
            make_success((8.0,)),   # /live/clip/get/length
            make_sent(),            # /live/clip/add/notes
        ]
        notes = [{'pitch': 60, 'time': 0.0, 'duration': 1.0, 'velocity': 100, 'mute': 0}]
        result = await server.add_notes_to_clip(0, 0, notes)
        assert "Added 1 notes" in result

    async def test_no_clip_returns_helpful_message(self, mock_send_command):
        mock_send_command.return_value = make_error('No clip')
        notes = [{'pitch': 60, 'time': 0.0, 'duration': 1.0}]
        result = await server.add_notes_to_clip(0, 0, notes)
        assert "create_clip" in result

    async def test_flat_note_encoding(self, mock_send_command):
        """Verify the flat list encoding: [pitch, time, duration, velocity, mute, ...]"""
        mock_send_command.side_effect = [make_success((4.0,)), make_sent()]
        notes = [
            {'pitch': 60, 'time': 0.0, 'duration': 0.5, 'velocity': 80, 'mute': 0},
            {'pitch': 64, 'time': 0.5, 'duration': 0.5, 'velocity': 90, 'mute': 0},
        ]
        await server.add_notes_to_clip(1, 2, notes)
        _, add_call = mock_send_command.call_args_list
        address, args = add_call[0][0], add_call[0][1]
        assert address == '/live/clip/add/notes'
        # First two elements are track_index, clip_index
        assert args[0] == 1
        assert args[1] == 2
        # Then flat note data: pitch, time, duration, velocity, mute × 2
        assert args[2:] == [60, 0.0, 0.5, 80, 0, 64, 0.5, 0.5, 90, 0]


# ---------------------------------------------------------------------------
# get_notes_from_clip
# ---------------------------------------------------------------------------

class TestGetNotesFromClip:
    async def test_returns_formatted_notes(self, mock_send_command):
        # Flat data after track/clip prefix: pitch, time, duration, velocity, mute
        flat = [60, 0.0, 1.0, 100, 0,   # note 1
                64, 1.0, 0.5, 80,  0]   # note 2
        mock_send_command.return_value = make_success(tuple(flat))
        result = await server.get_notes_from_clip(0, 0)
        assert "C4" in result
        assert "E4" in result
        assert "2 total" in result

    async def test_empty_clip(self, mock_send_command):
        mock_send_command.return_value = make_success(())
        result = await server.get_notes_from_clip(0, 0)
        assert "No notes" in result

    async def test_error_response(self, mock_send_command):
        mock_send_command.return_value = make_error()
        result = await server.get_notes_from_clip(0, 0)
        assert "Error" in result


# ---------------------------------------------------------------------------
# get_track_devices
# ---------------------------------------------------------------------------

class TestGetTrackDevices:
    async def test_returns_device_list(self, mock_send_command):
        mock_send_command.return_value = make_success(('Reverb', 'EQ Eight'))
        result = await server.get_track_devices(0)
        assert "[0] Reverb" in result
        assert "[1] EQ Eight" in result

    async def test_no_devices(self, mock_send_command):
        mock_send_command.return_value = make_success(())
        result = await server.get_track_devices(0)
        assert "No devices" in result


# ---------------------------------------------------------------------------
# get_device_parameters
# ---------------------------------------------------------------------------

class TestGetDeviceParameters:
    async def test_returns_name_value_pairs(self, mock_send_command):
        mock_send_command.side_effect = [
            make_success(('Decay', 'Mix')),       # names
            make_success((0.5, 1.0)),              # values
        ]
        result = await server.get_device_parameters(0, 0)
        assert "Decay" in result
        assert "0.5" in result
        assert "Mix" in result

    async def test_error(self, mock_send_command):
        mock_send_command.side_effect = [make_error(), make_error()]
        result = await server.get_device_parameters(0, 0)
        assert "Error" in result


# ---------------------------------------------------------------------------
# set_device_parameter
# ---------------------------------------------------------------------------

class TestSetDeviceParameter:
    async def test_success(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.set_device_parameter(0, 0, 2, 0.75)
        assert "0.75" in result

    async def test_error(self, mock_send_command):
        mock_send_command.return_value = make_error()
        result = await server.set_device_parameter(0, 0, 2, 0.75)
        assert "Error" in result


# ---------------------------------------------------------------------------
# get_song_tempo / set_song_tempo
# ---------------------------------------------------------------------------

class TestTempo:
    async def test_get_tempo(self, mock_send_command):
        mock_send_command.return_value = make_success((128.0,))
        result = await server.get_song_tempo()
        assert "128" in result

    async def test_get_tempo_error(self, mock_send_command):
        mock_send_command.return_value = make_error()
        result = await server.get_song_tempo()
        assert "Error" in result

    async def test_set_tempo(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.set_song_tempo(140.0)
        assert "140" in result
        mock_send_command.assert_called_once_with('/live/song/set/tempo', [140.0])

    async def test_set_tempo_error(self, mock_send_command):
        mock_send_command.return_value = make_error()
        result = await server.set_song_tempo(140.0)
        assert "Error" in result


# ---------------------------------------------------------------------------
# play_scene / stop_all_clips
# ---------------------------------------------------------------------------

class TestSceneAndClipControl:
    async def test_play_scene(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.play_scene(2)
        assert "2" in result
        mock_send_command.assert_called_once_with('/live/song/trigger_scene', [2])

    async def test_stop_all_clips(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.stop_all_clips()
        assert "Stopped" in result


# ---------------------------------------------------------------------------
# start_playback / stop_playback
# ---------------------------------------------------------------------------

class TestPlaybackControl:
    async def test_start_playback(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.start_playback()
        assert "started" in result.lower()
        mock_send_command.assert_called_once_with('/live/song/start_playing', [])

    async def test_stop_playback(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.stop_playback()
        assert "stopped" in result.lower()
        mock_send_command.assert_called_once_with('/live/song/stop_playing', [])

    async def test_start_playback_error(self, mock_send_command):
        mock_send_command.return_value = make_error('Transport locked')
        result = await server.start_playback()
        assert "Error" in result
        assert "Transport locked" in result

    async def test_stop_playback_error(self, mock_send_command):
        mock_send_command.return_value = make_error()
        result = await server.stop_playback()
        assert "Error" in result


# ---------------------------------------------------------------------------
# fire_clip / stop_clip
# ---------------------------------------------------------------------------

class TestClipFireStop:
    async def test_fire_clip_success(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.fire_clip(3, 1)
        assert "3" in result
        assert "1" in result
        mock_send_command.assert_called_once_with('/live/clip/fire', [3, 1])

    async def test_fire_clip_error(self, mock_send_command):
        mock_send_command.return_value = make_error('No clip')
        result = await server.fire_clip(3, 1)
        assert "Error" in result

    async def test_stop_clip_success(self, mock_send_command):
        mock_send_command.return_value = make_sent()
        result = await server.stop_clip(3, 1)
        assert "3" in result
        assert "1" in result
        mock_send_command.assert_called_once_with('/live/clip/stop', [3, 1])

    async def test_stop_clip_error(self, mock_send_command):
        mock_send_command.return_value = make_error()
        result = await server.stop_clip(3, 1)
        assert "Error" in result
