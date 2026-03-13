# Ableton Live MCP Server

Control Ableton Live with AI agents using natural language. This server connects AI tools like Claude to your Ableton Live session, letting you say things like *"prepare a set for recording a rock band"* and have it actually happen.

[![Control Ableton Live with LLMs](https://img.youtube.com/vi/12MzsQ3V7cs/hqdefault.jpg)](https://www.youtube.com/watch?v=12MzsQ3V7cs)

---

## How It Works

This project acts as a bridge between AI assistants and Ableton Live. Here's the big picture:

```
AI Agent (Claude, etc.)
        ↕
  MCP Server (this project)
        ↕
    OSC Daemon
        ↕
  Ableton Live (via AbletonOSC)
```

- **MCP** (Model Context Protocol) is the standard that lets AI agents use tools and talk to external software.
- **OSC** (Open Sound Control) is how software talks to Ableton Live.
- **AbletonOSC** is a free Ableton control surface that enables OSC communication.

---

## Prerequisites

Before you start, make sure you have:

1. **Ableton Live** installed and running
2. **Python 3.8 or newer** — [download here](https://www.python.org/downloads/)
3. **Git** — [download here](https://git-scm.com/downloads)
4. **uv** (a fast Python package manager) — install it by running this in your terminal:

   **Mac / Linux:**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   **Windows** (in PowerShell):
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   > **What's a terminal?** On Mac, open **Terminal** (press `Cmd+Space` and type "Terminal"). On Windows, open **PowerShell** (press `Win+S` and type "PowerShell").

---

## Step 1: Install AbletonOSC in Ableton Live

AbletonOSC is a free plugin that lets software communicate with Ableton. You need to install it once.

1. Go to the [AbletonOSC releases page](https://github.com/ideoforms/AbletonOSC/releases) and download the latest `.zip` file.
2. Unzip it. Inside you'll find a folder called `AbletonOSC`.
3. Copy that folder to your Ableton **MIDI Remote Scripts** directory:
   - **Mac:** `~/Library/Preferences/Ableton/Live x.x.x/User Remote Scripts/`
   - **Windows:** `C:\Users\[YourName]\AppData\Roaming\Ableton\Live x.x.x\User Remote Scripts\`

   > **Tip:** On Mac, the `Library` folder is hidden. In Finder, hold `Option` and click the **Go** menu — you'll see "Library" appear.

4. Open Ableton Live (or restart it if it was already open).
5. In Ableton, go to **Preferences → Link, Tempo & MIDI**.
6. Under **Control Surface**, select **AbletonOSC** from the dropdown. Leave Input and Output as **None**.
7. You should see a message in the Ableton status bar confirming AbletonOSC is active.

---

## Step 2: Download This Project

Open your terminal and run:

```bash
git clone https://github.com/your-username/ableton-live-mcp-server.git
cd ableton-live-mcp-server
```

Then install the dependencies:

```bash
uv sync
```

> This may take a minute the first time. It's downloading all the required Python packages.

---

## Step 3: Start the OSC Daemon

The OSC daemon is a background process that handles communication between the MCP server and Ableton Live. You need to keep it running in a terminal window whenever you're using this.

```bash
uv run osc_daemon.py
```

Leave this terminal window open. You should see it waiting for connections — that's normal.

---

## Step 4: Choose Your Setup

There are two ways to connect an AI agent to this server. Pick the one that fits your situation:

---

### Option A: Claude Desktop (Same Computer)

Use this if you're running Claude Desktop on the **same computer** as Ableton Live. This is the easiest setup for personal use.

**What is Claude Desktop?** It's the free downloadable Claude app from Anthropic. [Download it here](https://claude.ai/download).

> NOTE: You will need a Claude subscription (Pro is fine, Max will give you more usage. Try with Pro first to see if this is a good solution before shelling out $100/mo (in this economy!?)) to do this. 

#### Configure Claude Desktop

1. Open Claude Desktop.
2. Go to **Settings** (the gear icon or Claude menu).
3. Click **Developer** → **Edit Config**. This opens a file called `claude_desktop_config.json`.

   If it doesn't open automatically, find it yourself:
   - **Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

4. Add the following inside the file. Replace `/Users/bjunya/code/ableton-live-mcp-server` with the actual path to where you downloaded this project:

   ```json
   {
     "mcpServers": {
       "ableton-live": {
         "command": "/bin/sh",
         "args": [
           "-c",
           "cd /path/to/this/git/repo/ableton-live-mcp-server && uv run mcp_ableton_server.py"
         ]
       }
     }
   }
   ```

   > **How do I find my project path?** In your terminal, navigate to the project folder and run `pwd` (Mac/Linux) or `cd` (Windows). Copy the output — that's your path.

   > **Windows users:** Use `cmd /c` instead of `/bin/sh -c`, and use backslashes in your path, e.g.:
   > ```json
   > {
   >   "mcpServers": {
   >     "ableton-live": {
   >       "command": "cmd",
   >       "args": ["/c", "cd C:\\Users\\YourName\\path\\to\\this\\repo\\ableton-live-mcp-server && uv run mcp_ableton_server.py"]
   >     }
   >   }
   > }
   > ```

5. Save the file and **restart Claude Desktop**.

6. In Claude Desktop, you should now see a small hammer icon (🔨) near the chat input, indicating MCP tools are available. If you click it, you'll see Ableton Live tools listed.

#### Try It Out

Make sure both Ableton Live and the OSC daemon are running, then ask Claude:

- *"What tracks do I have in my current Ableton set?"*
- *"Prepare a set for recording a rock band with drums, bass, guitar, and vocals"*
- *"Set the BPM to 120"*
- *"Mute the drum track"*

---

### Option B: SSE Server (Remote Agents / Same Network)

Use this if you want an AI agent running on a **different device** (like a server, another computer, or a cloud agent) to connect to this MCP server over your local network. This uses SSE (Server-Sent Events) over HTTP.

**Examples of when you'd use this:**
- Running an agent framework like **OpenClaw**, **LangChain**, or **AutoGen** on a separate machine
- Building a custom AI workflow that connects to your Ableton setup remotely
- Testing the MCP server from another device on your network

#### Start the SSE Server

In a new terminal window (keep the OSC daemon running in the other one):

```bash
uv run run_sse_server.py --host 0.0.0.0 --port 8765
```

You'll see:
```
Starting Ableton Live MCP server (SSE) on http://0.0.0.0:8765/sse
Connect via: http://0.0.0.0:8765/sse
Press Ctrl+C to stop.
```

#### Find Your Computer's Local IP Address

The remote agent needs to know your computer's IP address on the local network.

> PROTIP: Use [Tailscale](https://tailscale.com/) and make your own network across the internet for remote access. You can use your Tailscale IP address between your Ableton host and your agent's machine

- **Mac:** Go to **System Settings → Network** and look for your IP address (usually starts with `192.168.x.x` or `10.0.x.x`).
- **Windows:** Open PowerShell and run `ipconfig`. Look for "IPv4 Address".
- **Terminal (any OS):** Run `ipconfig getifaddr en0` (Mac Wi-Fi) or `hostname -I` (Linux).

#### Connect Your Agent

Have your remote agent (OpenClaw, custom script, etc.) connect to:

```
http://YOUR_COMPUTER_IP:8765/sse
```

For example, if your Mac's IP is `192.168.1.42`:
```
http://192.168.1.42:8765/sse
```

> **Firewall note:** If the connection fails, you may need to allow port `8765` through your firewall. On Mac, go to **System Settings → Network → Firewall**. On Windows, search for "Windows Firewall" and add an inbound rule for port 8765.

#### Custom Host and Port

You can change the port if 8765 is already in use:

```bash
uv run run_sse_server.py --host 0.0.0.0 --port 9000
```

---

## Port Reference

Here's a summary of all the ports this project uses internally:

| Port  | What it's for |
|-------|---------------|
| 65432 | Internal socket between MCP server and OSC daemon |
| 11000 | OSC messages sent **to** Ableton Live |
| 11001 | OSC responses received **from** Ableton Live |
| 8765  | HTTP/SSE port for remote agents (Option B only) |

---

## Troubleshooting

**Claude Desktop doesn't show the hammer icon / Ableton tools**
- Make sure you saved `claude_desktop_config.json` correctly (valid JSON — no missing commas or brackets).
- Restart Claude Desktop completely.
- Make sure the path in the config actually points to where you downloaded the project.

**"Failed to connect to daemon" errors**
- Make sure `uv run osc_daemon.py` is running in a terminal.
- Don't close that terminal window while using the server.

**Ableton doesn't respond to commands**
- Make sure AbletonOSC is selected as a Control Surface in Ableton's preferences.
- Make sure Ableton Live is open and has a project loaded.
- Restart Ableton after installing AbletonOSC if you haven't already.

**Remote agent can't connect (Option B)**
- Double-check your computer's local IP address.
- Make sure you used `--host 0.0.0.0` (not `127.0.0.1`) when starting the SSE server.
- Check your firewall settings.

---

## Example Prompts to Try

Once everything is set up, here are some things you can ask the AI:

- *"List all the tracks in my Ableton set"*
- *"Create 4 MIDI tracks: Drums, Bass, Chords, Lead"*
- *"Set the tempo to 140 BPM"*
- *"Prepare a set to record a rock band"*
- *"Set the input routing of all tracks with 'voice' in the name to Ext. In 2"*
- *"Solo the bass track and mute everything else"*
- *"What devices are on the drum track?"*

While these prompts are nice and show off the basic functions of what you can do, I think there's potential to do way cooler stuff

## More Advanced Prompting Techniques

### Generating MIDI in Context
When I'm producing music, sometimes I'll need MIDI generated with a starter chord progression. In session view, I'll throw my melody on a particular scene and track and have Claude generate a basic chord progression that follows the melody and harmonizes with it

> I have a melody on Scene 2, Track "MELODY" - in the "CHORDS" track on Scene 2, generate a basic chord progression that follows the melody and harmonizes. Use basic counterpoint rules. Go for "artist name" vibes and increase the harmonic tension over 4 bars, but make sure this is loopable and can still resolve to tonic

### Revoice Chord Progressions

> I have a chord progression I wrote on a track named "track_name", scene "x" - revoice this chord progression and play with inversions to get it to sound "vibeszzzzz here" 

**^TIP:** You can totally drop in some music theory and Claude will handle the rest. I use this tool to generate starter harmonies just as a jumping off point. **9/10 times they will be total ass** - you yourself as a producer need to push the notes around. The notes should not push you around to "play it safe". Remember, **you** are the one in creative control here. **Fully generated by AI music is ass and will always be ass**

---

## Contributing

Found a bug or have an idea? Feel free to open an issue or pull request on GitHub.

---

## License

MIT License — see the `LICENSE` file for details.

---

## Acknowledgments

- [Model Context Protocol (MCP)](https://modelcontextprotocol.io)
- [AbletonOSC](https://github.com/ideoforms/AbletonOSC) by Daniel John Jones
- [python-osc](https://github.com/attwad/python-osc) for OSC handling
- Julien Bayle at [Structure Void](https://structure-void.com/) for endless inspiration and resources
