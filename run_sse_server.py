"""
Standalone SSE server for the Ableton Live MCP server.

Run this in a terminal to serve the MCP server over HTTP/SSE on a local port.
This is independent of Claude Desktop — useful for testing, alternative clients,
or any scenario where you want to control the server lifecycle yourself.

Usage:
    uv run run_sse_server.py
    uv run run_sse_server.py --port 8765
    uv run run_sse_server.py --host 0.0.0.0 --port 8765
"""

import argparse
from mcp_ableton_server import mcp, ableton_client

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ableton Live MCP Server (SSE mode)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port

    print(f"Starting Ableton Live MCP server (SSE) on http://{args.host}:{args.port}/sse", flush=True)
    print(f"Connect via: http://{args.host}:{args.port}/sse", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    try:
        mcp.run(transport="sse")
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        ableton_client.close()
