from mcp.server.fastmcp import FastMCP
import asyncio
import json
import socket
import struct
import sys
from typing import Optional, List


class AbletonClient:
    def __init__(self, host='127.0.0.1', port=65432):
        self.host = host
        self.port = port
        self.sock = None
        self.connected = False
        self._lock = asyncio.Lock()

    def _ensure_connected(self) -> bool:
        """Synchronous connect — called from within executor."""
        if self.connected and self.sock:
            return True
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10)
            self.sock.connect((self.host, self.port))
            self.connected = True
            print(f"Connected to OSC daemon at {self.host}:{self.port}", file=sys.stderr)
            return True
        except Exception as e:
            print(f"Failed to connect to daemon: {e}", file=sys.stderr)
            self.connected = False
            return False

    def _recv_all(self, n: int) -> bytes:
        """Read exactly n bytes from the socket, handling TCP fragmentation.

        TCP does not guarantee that a single recv() returns all requested bytes —
        large payloads (e.g. clips with many MIDI notes) can arrive in pieces.
        This method loops until exactly n bytes have been accumulated.
        Raises ConnectionError if the connection closes before n bytes are read.
        """
        buf = b''
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError('Connection closed by daemon before full message received')
            buf += chunk
        return buf

    def _send_recv(self, message: dict) -> dict:
        """Synchronous send + receive — run in executor to avoid blocking the event loop.

        Uses a 4-byte big-endian length prefix before every JSON payload so that
        the receiver always knows exactly how many bytes to read. This prevents
        both silent truncation (old recv(4096) limit) and fragmented-read bugs
        where TCP delivers a large message across multiple recv() calls.
        """
        if not self._ensure_connected():
            return {'status': 'error', 'message': 'Not connected to daemon'}
        try:
            payload = json.dumps(message).encode()
            self.sock.sendall(struct.pack('>I', len(payload)) + payload)
            raw_len = self._recv_all(4)
            msg_len = struct.unpack('>I', raw_len)[0]
            data = self._recv_all(msg_len)
            return json.loads(data.decode())
        except Exception as e:
            self.connected = False
            return {'status': 'error', 'message': str(e)}

    async def send_command(self, address: str, args: list = None) -> dict:
        """Send an OSC command via the daemon and return the response."""
        async with self._lock:
            message = {
                'command': 'send_message',
                'address': address,
                'args': args or []
            }
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._send_recv, message)

    def close(self):
        if self.sock:
            self.sock.close()
            self.connected = False


# Initialize the MCP server
mcp = FastMCP(
    "Ableton Live Controller",
    dependencies=["python-osc"],
    instructions="""
You are controlling Ableton Live via OSC through the MCP tools provided by this server.

CRITICAL — Track and scene indices are NOT stable:
Ableton track indices and scene indices shift whenever tracks or scenes are added, deleted,
or reordered. An index that was correct at the start of a conversation may point to a
completely different track by the time you use it.

RULES:
1. Never assume, cache, or reuse a track index across steps. Always resolve it fresh.
2. Before any operation that takes a track_index, call find_track_by_name() first to get
   the current live index. Use that returned index immediately — do not store it for later.
3. Before any operation that takes a scene_index, call find_scene_by_name() first to get
   the current live index.
4. If a user refers to a track by name (e.g. "the Bass track"), always look it up with
   find_track_by_name() — never guess the index.
5. If find_track_by_name() returns multiple matches, clarify with the user before proceeding.

Example workflow for "add a note to the Bass track":
  1. find_track_by_name("Bass")  → returns "index 2: Bass"
  2. get_clip_info(track_index=2, scene_index=0)  → verify clip exists
  3. add_notes_to_clip(track_index=2, ...)
""",
)

# Create Ableton client
ableton_client = AbletonClient()

# Note name lookup (prefers flats)
NOTE_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

def midi_to_note_name(pitch: int) -> str:
    return NOTE_NAMES[int(pitch) % 12] + str(int(pitch) // 12 - 1)

def strip_osc_prefix(data: list, *expected_prefix_ints) -> list:
    """
    AbletonOSC often prepends track_index and/or clip_index to response data.
    Strip them if present, using int comparison to handle float/int mismatches.
    """
    prefix = list(expected_prefix_ints)
    if len(data) >= len(prefix):
        if all(int(data[i]) == prefix[i] for i in range(len(prefix))):
            return data[len(prefix):]
    return data


# ----- TOOLS -----

@mcp.tool()
async def get_track_names(index_min: Optional[int] = None, index_max: Optional[int] = None) -> str:
    """
    Get the names of tracks in Ableton Live.

    Args:
        index_min: Optional minimum track index
        index_max: Optional maximum track index

    Returns:
        A formatted string containing track names
    """
    args = [index_min, index_max] if index_min is not None and index_max is not None else []
    response = await ableton_client.send_command('/live/song/get/track_names', args)

    if response.get('status') == 'success':
        data = response.get('data', ())
        if not data:
            return "No tracks found"
        return "Track Names: " + ", ".join(str(n) for n in data)
    else:
        return f"Error getting track names: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def find_track_by_name(name: str) -> str:
    """
    Find a track's index by searching for its name (case-insensitive, partial match).

    Args:
        name: The track name or partial name to search for

    Returns:
        Matching track indices and names
    """
    response = await ableton_client.send_command('/live/song/get/track_names', [])
    if response.get('status') == 'success':
        tracks = list(response.get('data', ()))
        matches = [
            f"index {i}: {t}" for i, t in enumerate(tracks)
            if name.lower() in str(t).lower()
        ]
        if not matches:
            return f"No tracks found matching '{name}'"
        return "\n".join(matches)
    else:
        return f"Error getting tracks: {response.get('message', 'Unknown error')}"


async def _fetch_all_scenes() -> list:
    """
    Internal helper: fetch all scenes as a list of (index, name) tuples.
    Stops at the first failure since scenes are contiguous in Ableton.
    """
    count_response = await ableton_client.send_command('/live/song/get/num_scenes', [])
    if count_response.get('status') == 'success':
        count_data = count_response.get('data', ())
        num_scenes = int(count_data[0]) if count_data else 16
    else:
        num_scenes = 16  # fallback if endpoint not supported

    scenes = []
    for i in range(num_scenes):
        r = await ableton_client.send_command('/live/scene/get/name', [i])
        if r.get('status') == 'success':
            data = strip_osc_prefix(list(r.get('data', ())), i)
            scene_name = str(data[0]) if data else ''
            scenes.append((i, scene_name))
        else:
            break
    return scenes


@mcp.tool()
async def get_scene_names() -> str:
    """
    Get the names of all scenes in Ableton Live's session view.

    Returns:
        A formatted string listing every scene index and name
    """
    scenes = await _fetch_all_scenes()
    if not scenes:
        return "Could not retrieve scene names"
    return "Scene Names:\n" + "\n".join(f"  {i}: '{name}'" for i, name in scenes)


@mcp.tool()
async def find_scene_by_name(name: str) -> str:
    """
    Find a scene's index by searching for its name (case-insensitive, partial match).
    Use this instead of guessing scene indices.

    Args:
        name: The scene name or partial name to search for (e.g. "BREAK", "DROP")

    Returns:
        Matching scene indices and names
    """
    scenes = await _fetch_all_scenes()
    if not scenes:
        return "Could not retrieve scene names"

    matches = [f"index {i}: '{s}'" for i, s in scenes if name.lower() in s.lower()]
    if not matches:
        all_scenes = ", ".join(f"{i}:'{s}'" for i, s in scenes)
        return f"No scenes found matching '{name}'. All scenes: {all_scenes}"
    return "\n".join(matches)


@mcp.tool()
async def get_clip_info(track_index: int, scene_index: int) -> str:
    """
    Get the name and length of a clip at a given track/scene slot.
    Use this to check whether a clip exists before writing to it.
    IMPORTANT: Track and scene indices shift often. Call find_track_by_name() and
    find_scene_by_name() first to get current indices — never assume or reuse old ones.

    Args:
        track_index: Zero-based index of the track
        scene_index: Zero-based index of the scene

    Returns:
        Clip name, length in beats, or a message if no clip exists
    """
    name_response = await ableton_client.send_command(
        '/live/clip/get/name', [track_index, scene_index]
    )
    length_response = await ableton_client.send_command(
        '/live/clip/get/length', [track_index, scene_index]
    )

    if name_response.get('status') != 'success' and length_response.get('status') != 'success':
        return f"No clip at track {track_index}, scene {scene_index}"

    name_data = strip_osc_prefix(list(name_response.get('data', ())), track_index, scene_index)
    length_data = strip_osc_prefix(list(length_response.get('data', ())), track_index, scene_index)

    clip_name = name_data[0] if name_data else "(unnamed)"
    clip_length = length_data[0] if length_data else "unknown"

    return f"Clip at track {track_index}, scene {scene_index}: name='{clip_name}', length={clip_length} beats"


@mcp.tool()
async def set_clip_name(track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.
    IMPORTANT: Track indices shift often. Call find_track_by_name() first to get the current index.

    Args:
        track_index: Zero-based index of the track
        clip_index: Zero-based index of the clip slot
        name: The new name for the clip

    Returns:
        Status message
    """
    response = await ableton_client.send_command(
        '/live/clip/set/name', [track_index, clip_index, name]
    )
    if response.get('status') in ('success', 'sent'):
        return f"Named clip at track {track_index}, clip {clip_index} -> '{name}'"
    else:
        return f"Error setting clip name: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def delete_clip(track_index: int, scene_index: int) -> str:
    """
    Delete a clip from a clip slot. Use this to undo accidental writes.
    IMPORTANT: Track and scene indices shift often. Call find_track_by_name() and
    find_scene_by_name() first to get current indices — never assume or reuse old ones.

    Args:
        track_index: Zero-based index of the track
        scene_index: Zero-based index of the scene

    Returns:
        Status message
    """
    response = await ableton_client.send_command(
        '/live/clip_slot/delete_clip', [track_index, scene_index]
    )
    if response.get('status') in ('success', 'sent'):
        return f"Deleted clip at track {track_index}, scene {scene_index}"
    else:
        return f"Error deleting clip: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def create_clip(track_index: int, scene_index: int, length_beats: float) -> str:
    """
    Create an empty MIDI clip in a clip slot in Ableton's session view.
    IMPORTANT: Track and scene indices shift often. Call find_track_by_name() and
    find_scene_by_name() first to get current indices — never assume or reuse old ones.

    Args:
        track_index: Zero-based index of the track
        scene_index: Zero-based index of the scene (row in session view)
        length_beats: Length of the clip in beats (4 beats = 1 bar at 4/4)

    Returns:
        Status message
    """
    response = await ableton_client.send_command(
        '/live/clip_slot/create_clip',
        [track_index, scene_index, length_beats]
    )
    if response.get('status') in ('success', 'sent'):
        return f"Created {length_beats}-beat clip at track {track_index}, scene {scene_index}"
    else:
        return f"Error creating clip: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def add_notes_to_clip(track_index: int, clip_index: int, notes: List[dict]) -> str:
    """
    Add MIDI notes to an existing clip in Ableton Live.
    IMPORTANT: The clip must already exist — call create_clip first if needed.
    IMPORTANT: Track indices shift often. Call find_track_by_name() first to get the current index.

    Args:
        track_index: Zero-based index of the track
        clip_index: Zero-based index of the clip slot
        notes: List of note dicts, each with keys:
               - pitch (int): MIDI note number (0-127)
               - time (float): Start time in beats from clip start
               - duration (float): Duration in beats
               - velocity (int): Note velocity (0-127)
               - mute (int): 0 = active, 1 = muted

    Returns:
        Status message
    """
    # Pre-check: verify clip exists before attempting to write
    check = await ableton_client.send_command(
        '/live/clip/get/length', [track_index, clip_index]
    )
    if check.get('status') != 'success':
        return (
            f"No clip found at track {track_index}, clip {clip_index}. "
            f"Call create_clip first."
        )

    # AbletonOSC expects: track_id, clip_id, then flat list of [pitch, time, duration, velocity, mute, ...]
    flat_notes = []
    for note in notes:
        flat_notes.extend([
            note['pitch'],
            note['time'],
            note['duration'],
            note.get('velocity', 100),
            note.get('mute', 0)
        ])

    response = await ableton_client.send_command(
        '/live/clip/add/notes',
        [track_index, clip_index] + flat_notes
    )
    if response.get('status') in ('success', 'sent'):
        return f"Added {len(notes)} notes to clip at track {track_index}, clip {clip_index}"
    else:
        return f"Error adding notes: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def get_notes_from_clip(track_index: int, clip_index: int) -> str:
    """
    Get all MIDI notes from an existing clip in Ableton Live.
    IMPORTANT: Track indices shift often. Call find_track_by_name() first to get the current index.

    Args:
        track_index: Zero-based index of the track
        clip_index: Zero-based index of the clip slot

    Returns:
        A formatted string listing all notes with pitch, time, duration, velocity
    """
    response = await ableton_client.send_command(
        '/live/clip/get/notes',
        [track_index, clip_index]
    )
    if response.get('status') == 'success':
        data = list(response.get('data', ()))
        if not data:
            return "No notes found in clip"
        # BUG FIX: use int() comparison to handle float/int mismatch from OSC
        data = strip_osc_prefix(data, track_index, clip_index)
        if not data:
            return "Clip exists but contains no notes"
        # Remaining data is flat list: pitch, time, duration, velocity, mute, ...
        notes = []
        for i in range(0, len(data) - 4, 5):
            chunk = data[i:i+5]
            if len(chunk) < 5:
                break
            pitch, time, duration, velocity, mute = chunk
            notes.append(
                f"  {midi_to_note_name(pitch)} (MIDI {int(pitch)}) "
                f"| beat {float(time):.2f} | dur {float(duration):.2f} | vel {int(velocity)}"
            )
        return f"Notes in clip ({len(notes)} total):\n" + "\n".join(notes)
    else:
        return f"Error getting notes: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def get_track_devices(track_index: int) -> str:
    """
    Get the list of devices on a track.
    IMPORTANT: Track indices shift often. Call find_track_by_name() first to get the current index.

    Args:
        track_index: Zero-based index of the track

    Returns:
        A formatted string listing device names and their indices
    """
    response = await ableton_client.send_command('/live/track/get/devices', [track_index])
    if response.get('status') == 'success':
        data = response.get('data', ())
        if not data:
            return "No devices found on track"
        devices = list(data)
        return "\n".join(f"[{i}] {name}" for i, name in enumerate(devices))
    else:
        return f"Error getting devices: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def get_device_parameters(track_index: int, device_index: int) -> str:
    """
    Get all parameter names and values for a device on a track.
    IMPORTANT: Track indices shift often. Call find_track_by_name() first to get the current index.

    Args:
        track_index: Zero-based index of the track
        device_index: Zero-based index of the device on the track

    Returns:
        A formatted string listing parameter indices, names, and current values
    """
    names_response = await ableton_client.send_command(
        '/live/device/get/parameters/name', [track_index, device_index]
    )
    values_response = await ableton_client.send_command(
        '/live/device/get/parameters/value', [track_index, device_index]
    )

    if names_response.get('status') == 'success' and values_response.get('status') == 'success':
        names = list(names_response.get('data', ()))
        values = list(values_response.get('data', ()))
        lines = [f"[{i}] {name} = {value}" for i, (name, value) in enumerate(zip(names, values))]
        return "\n".join(lines)
    else:
        return f"Error getting parameters: {names_response.get('message', values_response.get('message', 'Unknown error'))}"


@mcp.tool()
async def set_device_parameter(track_index: int, device_index: int, parameter_index: int, value: float) -> str:
    """
    Set the value of a device parameter.
    IMPORTANT: Track indices shift often. Call find_track_by_name() first to get the current index.

    Args:
        track_index: Zero-based index of the track
        device_index: Zero-based index of the device on the track
        parameter_index: Zero-based index of the parameter
        value: The value to set

    Returns:
        Status message
    """
    response = await ableton_client.send_command(
        '/live/device/set/parameter/value',
        [track_index, device_index, parameter_index, value]
    )
    if response.get('status') in ('success', 'sent'):
        return f"Set parameter {parameter_index} to {value} on device {device_index}, track {track_index}"
    else:
        return f"Error setting parameter: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def get_song_tempo() -> str:
    """
    Get the current tempo of the Ableton Live session in BPM.

    Returns:
        Current tempo as a string
    """
    response = await ableton_client.send_command('/live/song/get/tempo', [])
    if response.get('status') == 'success':
        data = response.get('data', ())
        tempo = float(data[0]) if data else None
        if tempo is not None:
            return f"Current tempo: {tempo:.2f} BPM"
        return "Tempo data not available"
    else:
        return f"Error getting tempo: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def set_song_tempo(bpm: float) -> str:
    """
    Set the tempo of the Ableton Live session.

    Args:
        bpm: Tempo in beats per minute (e.g. 120.0)

    Returns:
        Status message
    """
    response = await ableton_client.send_command('/live/song/set/tempo', [bpm])
    if response.get('status') in ('success', 'sent'):
        return f"Tempo set to {bpm:.2f} BPM"
    else:
        return f"Error setting tempo: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def play_scene(scene_index: int) -> str:
    """
    Trigger (play) a scene in Ableton Live's session view.
    IMPORTANT: Scene indices shift often. Call find_scene_by_name() first to get the current index.

    Args:
        scene_index: Zero-based index of the scene to trigger

    Returns:
        Status message
    """
    response = await ableton_client.send_command('/live/song/trigger_scene', [scene_index])
    if response.get('status') in ('success', 'sent'):
        return f"Triggered scene {scene_index}"
    else:
        return f"Error triggering scene: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def stop_all_clips() -> str:
    """
    Stop all currently playing clips in Ableton Live.

    Returns:
        Status message
    """
    response = await ableton_client.send_command('/live/song/stop_all_clips', [])
    if response.get('status') in ('success', 'sent'):
        return "Stopped all clips"
    else:
        return f"Error stopping clips: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def start_playback() -> str:
    """
    Start playback of the Ableton Live session (press Play).

    Returns:
        Status message
    """
    response = await ableton_client.send_command('/live/song/start_playing', [])
    if response.get('status') in ('success', 'sent'):
        return "Playback started"
    else:
        return f"Error starting playback: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def stop_playback() -> str:
    """
    Stop playback of the Ableton Live session (press Stop).

    Returns:
        Status message
    """
    response = await ableton_client.send_command('/live/song/stop_playing', [])
    if response.get('status') in ('success', 'sent'):
        return "Playback stopped"
    else:
        return f"Error stopping playback: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def fire_clip(track_index: int, clip_index: int) -> str:
    """
    Fire (launch) a specific clip slot in Ableton Live's session view.
    This is more granular than play_scene — it launches a single clip.
    IMPORTANT: Track indices shift often. Call find_track_by_name() first to get the current index.

    Args:
        track_index: Zero-based index of the track
        clip_index: Zero-based index of the clip slot (scene row)

    Returns:
        Status message
    """
    response = await ableton_client.send_command('/live/clip/fire', [track_index, clip_index])
    if response.get('status') in ('success', 'sent'):
        return f"Fired clip at track {track_index}, slot {clip_index}"
    else:
        return f"Error firing clip: {response.get('message', 'Unknown error')}"


@mcp.tool()
async def stop_clip(track_index: int, clip_index: int) -> str:
    """
    Stop a specific clip playing in Ableton Live's session view.
    IMPORTANT: Track indices shift often. Call find_track_by_name() first to get the current index.

    Args:
        track_index: Zero-based index of the track
        clip_index: Zero-based index of the clip slot (scene row)

    Returns:
        Status message
    """
    response = await ableton_client.send_command('/live/clip/stop', [track_index, clip_index])
    if response.get('status') in ('success', 'sent'):
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    else:
        return f"Error stopping clip: {response.get('message', 'Unknown error')}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Ableton Live MCP Server")
    parser.add_argument("--sse", action="store_true", help="Run in SSE mode (HTTP server) instead of stdio")
    parser.add_argument("--port", type=int, default=8765, help="Port for SSE mode (default: 8765)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host for SSE mode (default: 127.0.0.1)")
    args = parser.parse_args()

    try:
        if args.sse:
            mcp.settings.host = args.host
            mcp.settings.port = args.port
            print(f"Starting MCP server in SSE mode on {args.host}:{args.port}", flush=True)
            mcp.run(transport="sse")
        else:
            mcp.run()
    finally:
        ableton_client.close()
