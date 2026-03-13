from mcp.server.fastmcp import FastMCP
import asyncio
import json
import socket
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

    def _send_recv(self, message: dict) -> dict:
        """Synchronous send + receive — run in executor to avoid blocking the event loop."""
        if not self._ensure_connected():
            return {'status': 'error', 'message': 'Not connected to daemon'}
        try:
            self.sock.sendall(json.dumps(message).encode())
            data = self.sock.recv(4096)
            if not data:
                self.connected = False
                return {'status': 'error', 'message': 'No response from daemon'}
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
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._send_recv, message)

    def close(self):
        if self.sock:
            self.sock.close()
            self.connected = False


# Initialize the MCP server
mcp = FastMCP("Ableton Live Controller", dependencies=["python-osc"])

# Create Ableton client
ableton_client = AbletonClient()


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
async def create_clip(track_index: int, scene_index: int, length_beats: float) -> str:
    """
    Create an empty MIDI clip in a clip slot in Ableton's session view.

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
async def get_track_devices(track_index: int) -> str:
    """
    Get the list of devices on a track.

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


if __name__ == "__main__":
    try:
        mcp.run()
    finally:
        ableton_client.close()
