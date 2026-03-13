# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## What This Project Does

Bridges AI agents (Claude, custom agents) to Ableton Live via the Model Context Protocol (MCP).

```
AI Agent (Claude Desktop / SSE client)
        ↕ MCP over stdio or HTTP/SSE
mcp_ableton_server.py
        ↕ JSON over TCP socket (port 65432)
osc_daemon.py
        ↕ OSC over UDP (ports 11000/11001)
Ableton Live + AbletonOSC plugin
```

## Commands

```bash
uv sync                          # Install dependencies
uv run osc_daemon.py             # Start OSC bridge daemon (must be running)
uv run mcp_ableton_server.py     # Run MCP server in stdio mode (for Claude Desktop)
uv run run_sse_server.py --host 0.0.0.0 --port 8765  # Run as HTTP/SSE server
```

No tests exist in this repo.

## Architecture

Three files, each with a single responsibility:

**`osc_daemon.py`** — Runs as a background process. Opens a TCP server on port 65432 (accepts connections from the MCP server), an OSC UDP client sending to Ableton on port 11000, and an OSC UDP server receiving from Ableton on port 11001. Uses a FIFO asyncio queue per OSC address to match responses to requests. "Set" commands are fire-and-forget; "get" commands wait up to 5 seconds for a response.

**`mcp_ableton_server.py`** — The MCP server. Uses `fastmcp`. Contains an `AbletonClient` class (TCP socket to the OSC daemon) and ~42 MCP tool functions. The FastMCP server is initialized with an embedded instruction string (lines 69–91) warning AI agents about index instability — track/scene indices shift when items are added, deleted, or reordered. Tools always recommend using `find_track_by_name()` before operating on a track. MIDI notes are represented as flat lists: `[pitch, time, duration, velocity, mute, ...]`.

**`run_sse_server.py`** — Thin wrapper that re-uses `mcp` and `ableton_client` from `mcp_ableton_server` and runs the server in SSE/HTTP mode instead of stdio mode.

## Key Constraints

- The OSC daemon must be running before the MCP server starts.
- Track/scene indices are unstable — always resolve by name before use.
- TCP socket buffer is 65536 bytes to handle large MIDI clip payloads.
- Requires Python ≥ 3.10; managed with `uv`.
