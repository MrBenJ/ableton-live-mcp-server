# osc_daemon.py
import asyncio
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.dispatcher import Dispatcher
import json
import struct
from typing import Optional, Dict, Any, List

class AbletonOSCDaemon:
    def __init__(self,
                 socket_host='127.0.0.1', socket_port=65432,
                 ableton_host='127.0.0.1', ableton_port=11000,
                 receive_port=11001):
        self.socket_host = socket_host
        self.socket_port = socket_port
        self.ableton_host = ableton_host
        self.ableton_port = ableton_port
        self.receive_port = receive_port

        # Initialize OSC client for Ableton
        self.osc_client = SimpleUDPClient(ableton_host, ableton_port)

        # Each address maps to a FIFO queue of futures.
        # Using a list per address so concurrent requests to the same endpoint
        # don't clobber each other — responses are matched in arrival order.
        self.pending_responses: Dict[str, List[asyncio.Future]] = {}

        # Initialize OSC server dispatcher
        self.dispatcher = Dispatcher()
        self.dispatcher.set_default_handler(self.handle_ableton_message)

    def handle_ableton_message(self, address: str, *args):
        """Handle incoming OSC messages from Ableton."""
        print(f"[ABLETON MESSAGE] Address: {address}, Args: {args}")

        # Resolve the oldest pending future for this address (FIFO).
        if address in self.pending_responses and self.pending_responses[address]:
            future = self.pending_responses[address].pop(0)
            if not future.done():
                future.set_result({
                    'status': 'success',
                    'address': address,
                    'data': args
                })
            # Clean up the address key if the list is now empty
            if not self.pending_responses[address]:
                del self.pending_responses[address]

    async def start(self):
        """Start both the socket server and OSC server."""
        # Start OSC server to receive Ableton messages.
        # asyncio.get_running_loop() is required in Python 3.10+;
        # get_event_loop() is deprecated and will raise a DeprecationWarning.
        self.osc_server = AsyncIOOSCUDPServer(
            (self.socket_host, self.receive_port),
            self.dispatcher,
            asyncio.get_running_loop()
        )
        await self.osc_server.create_serve_endpoint()

        # Start socket server for MCP communication
        server = await asyncio.start_server(
            self.handle_socket_client,
            self.socket_host,
            self.socket_port
        )
        print(f"Ableton OSC Daemon listening on {self.socket_host}:{self.socket_port}")
        print(f"OSC Server receiving on {self.socket_host}:{self.receive_port}")
        print(f"Sending to Ableton on {self.ableton_host}:{self.ableton_port}")

        async with server:
            await server.serve_forever()

    def _write_response(self, writer, response: dict):
        """Write a length-prefixed JSON response to the client.

        Every message is prefixed with a 4-byte big-endian unsigned int indicating
        the payload length. The MCP client's _recv_all() reads that header first,
        then reads exactly that many bytes — eliminating both the old 4096-byte
        truncation limit and silent fragmented-read failures on large payloads.
        """
        payload = json.dumps(response).encode()
        writer.write(struct.pack('>I', len(payload)) + payload)

    async def handle_socket_client(self, reader, writer):
        """Handle incoming socket connections from MCP server."""
        client_address = writer.get_extra_info('peername')
        print(f"[NEW CONNECTION] Client connected from {client_address}")

        try:
            while True:
                # Read the 4-byte length header first. IncompleteReadError means
                # the client disconnected cleanly — exit the loop.
                try:
                    raw_len = await reader.readexactly(4)
                except asyncio.IncompleteReadError:
                    break

                msg_len = struct.unpack('>I', raw_len)[0]

                try:
                    data = await reader.readexactly(msg_len)
                except asyncio.IncompleteReadError:
                    print(f"[CONNECTION ERROR] Client {client_address} disconnected mid-message")
                    break

                try:
                    message = json.loads(data.decode())
                    print(f"[RECEIVED MESSAGE] From {client_address}: {message}")

                    command = message.get('command')

                    if command == 'send_message':
                        # Extract OSC message details
                        address = message.get('address')
                        args = message.get('args', [])

                        # For commands that expect responses, set up a future
                        if address.startswith(('/live/device/get', '/live/scene/get', '/live/view/get', '/live/clip/get', '/live/clip_slot/get', '/live/track/get', '/live/song/get', '/live/api/get', '/live/application/get', '/live/test', '/live/error')):
                            # Create a future and enqueue it for this address.
                            # get_running_loop() is the correct modern API.
                            future = asyncio.get_running_loop().create_future()
                            if address not in self.pending_responses:
                                self.pending_responses[address] = []
                            self.pending_responses[address].append(future)

                            # Send to Ableton
                            self.osc_client.send_message(address, args)

                            try:
                                # Wait for response with timeout
                                response = await asyncio.wait_for(future, timeout=5.0)
                                print(f"[OSC RESPONSE] Received: {response}")
                                self._write_response(writer, response)
                            except asyncio.TimeoutError:
                                # future was cancelled by wait_for; remove it from
                                # the queue so a late Ableton response doesn't
                                # resolve a future nobody is waiting on.
                                if address in self.pending_responses:
                                    try:
                                        self.pending_responses[address].remove(future)
                                    except ValueError:
                                        pass
                                    if not self.pending_responses[address]:
                                        del self.pending_responses[address]
                                response = {
                                    'status': 'error',
                                    'message': f'Timeout waiting for response to {address}'
                                }
                                print(f"[OSC TIMEOUT] {response}")
                                self._write_response(writer, response)

                        else:
                            # For commands that don't expect responses
                            self.osc_client.send_message(address, args)
                            self._write_response(writer, {'status': 'sent'})

                    elif command == 'get_status':
                        response = {
                            'status': 'ok',
                            'ableton_port': self.ableton_port,
                            'receive_port': self.receive_port
                        }
                        print(f"[STATUS REQUEST] Responding with: {response}")
                        self._write_response(writer, response)
                    else:
                        print(f"[UNKNOWN COMMAND] Received: {message}")
                        self._write_response(writer, {'status': 'error', 'message': 'Unknown command'})

                    await writer.drain()

                except json.JSONDecodeError:
                    print(f"[JSON ERROR] Could not decode message: {data}")
                    self._write_response(writer, {'status': 'error', 'message': 'Invalid JSON'})
                    await writer.drain()

        except Exception as e:
            print(f"[CONNECTION ERROR] Error handling client: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            print(f"[CONNECTION CLOSED] Client {client_address} disconnected")

if __name__ == "__main__":
    daemon = AbletonOSCDaemon()
    asyncio.run(daemon.start())
