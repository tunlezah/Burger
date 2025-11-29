import asyncio
import logging
import os
import subprocess
import socket
import re
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse

import pychromecast
import zeroconf

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AudioBridge")

PORT = 8000
STREAM_ENDPOINT = "/live.mp3"


# --- Global State ---
class SystemState:
    def __init__(self):
        self.chromecasts = {}  # uuid_str -> Chromecast object
        self.selected_cast_uuid = None
        self.cast_browser = None
        self.zconf = None
        self.ffmpeg_process = None
        self.is_streaming = False
        self.active_connections: List[WebSocket] = []
        self.current_rms = 0
        self.bt_devices = []
        self.bt_connected: Optional[str] = None  # FIX #1: Track connected BT device
        self.current_audio_source: Optional[str] = None  # Track which source FFmpeg is using


state = SystemState()


# --- Helper Functions ---

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


async def get_connected_bluetooth_device() -> Optional[str]:
    """Check for currently connected Bluetooth audio device."""
    try:
        # Method 1: Check bluetoothctl for connected devices
        proc = await asyncio.create_subprocess_shell(
            "bluetoothctl info 2>/dev/null | grep -E '(Name|Connected)' || true",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        
        if "Connected: yes" in output:
            name_match = re.search(r"Name:\s*(.+)", output)
            if name_match:
                return name_match.group(1).strip()
        
        # Method 2: Check PipeWire/PulseAudio for Bluetooth sources
        proc2 = await asyncio.create_subprocess_shell(
            "pactl list sources short 2>/dev/null | grep -i 'bluez' || true",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout2, _ = await proc2.communicate()
        
        if stdout2.decode().strip():
            # Extract device name from bluez source
            proc3 = await asyncio.create_subprocess_shell(
                "pactl list sources 2>/dev/null | grep -A 30 'bluez' | grep 'device.description' | head -1 || true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            stdout3, _ = await proc3.communicate()
            desc_match = re.search(r'device\.description\s*=\s*"([^"]+)"', stdout3.decode())
            if desc_match:
                return desc_match.group(1)
            return "Bluetooth Device"
        
        return None
    except Exception as e:
        logger.error(f"Error checking Bluetooth connection: {e}")
        return None


async def broadcast_status():
    """Sends current state to all connected WebSockets."""
    cast_list = []
    if state.cast_browser:
        for uuid, cast_info in state.cast_browser.devices.items():
            cast_list.append({
                "uuid": str(uuid),
                "name": cast_info.friendly_name,
                "model": cast_info.model_name
            })

    # FIX #1: Include bt_connected in status
    status = {
        "streaming": state.is_streaming,
        "selected_cast": state.selected_cast_uuid,
        "rms": state.current_rms,
        "bt_devices": state.bt_devices,
        "bt_connected": state.bt_connected,  # Added this field
        "casts": cast_list
    }

    to_remove = []
    for connection in state.active_connections:
        try:
            await connection.send_json(status)
        except Exception:
            to_remove.append(connection)

    for c in to_remove:
        if c in state.active_connections:
            state.active_connections.remove(c)


# --- Audio Pipeline ---

async def audio_monitor_loop():
    """Parses FFMPEG stderr to extract RMS levels for the UI."""
    while True:
        if state.ffmpeg_process and state.ffmpeg_process.stderr:
            try:
                line = await asyncio.to_thread(state.ffmpeg_process.stderr.readline)
                if not line:
                    await asyncio.sleep(0.5)
                    continue

                line_str = line.decode('utf-8', errors='ignore')

                # FIX #3: Updated to parse lavfi.astats output format
                # The astats filter with metadata=1 outputs like: lavfi.astats.Overall.RMS_level=-20.5
                if "RMS" in line_str or "rms" in line_str.lower():
                    # Try multiple patterns
                    match = re.search(r"RMS[_\s]?level[:\s=]+([-\d.]+)", line_str, re.IGNORECASE)
                    if not match:
                        match = re.search(r"lavfi\.astats\.\w+\.RMS_level=([-\d.]+)", line_str)
                    
                    if match:
                        db_val = float(match.group(1))
                        # Convert dB to percentage (0-100)
                        # -60dB = 0%, 0dB = 100%
                        linear = max(0, min(100, (db_val + 60) * (100 / 60)))
                        state.current_rms = int(linear)
            except Exception as e:
                logger.error(f"Error reading ffmpeg stderr: {e}")
                await asyncio.sleep(1)
        else:
            state.current_rms = 0
            await asyncio.sleep(0.5)


def get_bluetooth_audio_source() -> Optional[str]:
    """Get the Bluetooth audio source name for PulseAudio/PipeWire."""
    try:
        result = subprocess.run(
            ["pactl", "list", "sources", "short"],
            capture_output=True, text=True, timeout=5
        )
        
        logger.info(f"Available audio sources:\n{result.stdout}")
        
        # Look for Bluetooth sources in order of preference
        bt_sources = []
        for line in result.stdout.splitlines():
            lower_line = line.lower()
            # Look for bluez sources (direct Bluetooth)
            if "bluez" in lower_line:
                parts = line.split()
                if len(parts) >= 2:
                    source_name = parts[1]
                    # Prefer A2DP sources
                    if "a2dp" in lower_line:
                        bt_sources.insert(0, source_name)
                    else:
                        bt_sources.append(source_name)
        
        if bt_sources:
            logger.info(f"Found Bluetooth sources: {bt_sources}, using: {bt_sources[0]}")
            return bt_sources[0]
        
        # If no direct Bluetooth source, look for a monitor of a Bluetooth sink
        # This captures audio being played TO a Bluetooth device
        result_sinks = subprocess.run(
            ["pactl", "list", "sinks", "short"],
            capture_output=True, text=True, timeout=5
        )
        
        for line in result_sinks.stdout.splitlines():
            if "bluez" in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    sink_name = parts[1]
                    monitor_name = sink_name + ".monitor"
                    logger.info(f"Found Bluetooth sink monitor: {monitor_name}")
                    return monitor_name
        
        logger.warning("No Bluetooth audio source found")
        return None
    except Exception as e:
        logger.error(f"Error getting Bluetooth source: {e}")
        return None


def get_default_audio_source() -> str:
    """Get the default audio source, with fallback logic."""
    try:
        # First try to get the default source
        result = subprocess.run(
            ["pactl", "get-default-source"],
            capture_output=True, text=True, timeout=5
        )
        default_source = result.stdout.strip()
        if default_source:
            logger.info(f"Default audio source: {default_source}")
            return default_source
    except Exception as e:
        logger.error(f"Error getting default source: {e}")
    
    return "default"


def start_ffmpeg_stream():
    """Starts FFMPEG to capture Bluetooth/default audio and encode to MP3."""
    if state.ffmpeg_process:
        logger.info("FFmpeg already running")
        return

    # Try to use Bluetooth source if available
    bt_source = get_bluetooth_audio_source()
    
    if bt_source:
        input_source = bt_source
        logger.info(f"Using Bluetooth audio source: {input_source}")
    else:
        input_source = get_default_audio_source()
        logger.warning(f"No Bluetooth source found, using default: {input_source}")
    
    # Store the source being used for debugging
    state.current_audio_source = input_source
    
    # FFmpeg command - simpler version without astats for reliability
    cmd = [
        "ffmpeg",
        "-f", "pulse",
        "-i", input_source,
        "-ac", "2",
        "-ar", "44100",
        "-b:a", "192k",
        "-f", "mp3",
        "-fflags", "+nobuffer",
        "-flags", "+low_delay",
        "pipe:1"
    ]

    logger.info(f"Starting FFMPEG: {' '.join(cmd)}")

    try:
        state.ffmpeg_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=4096
        )
        state.is_streaming = True
        logger.info(f"FFmpeg started with PID: {state.ffmpeg_process.pid}")
        
        # Start a background task to log FFmpeg errors
        import threading
        def log_ffmpeg_stderr():
            try:
                for line in state.ffmpeg_process.stderr:
                    line_str = line.decode('utf-8', errors='ignore').strip()
                    if line_str:
                        logger.debug(f"FFmpeg: {line_str}")
            except:
                pass
        
        stderr_thread = threading.Thread(target=log_ffmpeg_stderr, daemon=True)
        stderr_thread.start()
        
    except Exception as e:
        logger.error(f"Failed to start FFmpeg: {e}")
        state.ffmpeg_process = None
        state.is_streaming = False


def stop_ffmpeg_stream():
    if state.ffmpeg_process:
        state.ffmpeg_process.terminate()
        try:
            state.ffmpeg_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            state.ffmpeg_process.kill()
        state.ffmpeg_process = None
    state.is_streaming = False


async def stream_generator():
    """Yields data from FFMPEG stdout to the HTTP client."""
    start_ffmpeg_stream()
    try:
        while True:
            if not state.ffmpeg_process:
                break
            # FIX #4: Use asyncio.to_thread for non-blocking read
            data = await asyncio.to_thread(state.ffmpeg_process.stdout.read, 4096)
            if not data:
                break
            yield data
    except Exception as e:
        logger.error(f"Streaming error: {e}")


# --- Bluetooth Management ---

async def scan_bluetooth_devices():
    """Scans for devices using bluetoothctl."""
    proc = await asyncio.create_subprocess_shell(
        "bluetoothctl --timeout 15 scan on",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await proc.wait()

    proc_info = await asyncio.create_subprocess_shell(
        "bluetoothctl devices",
        stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc_info.communicate()

    devices = []
    for line in stdout.decode().splitlines():
        parts = line.split(" ", 2)
        if len(parts) >= 3:
            devices.append({"mac": parts[1], "name": parts[2]})

    state.bt_devices = devices
    return devices


async def set_discoverable():
    await asyncio.create_subprocess_shell("bluetoothctl discoverable on")
    await asyncio.create_subprocess_shell("bluetoothctl pairable on")
    await asyncio.create_subprocess_shell("bluetoothctl agent NoInputNoOutput")
    await asyncio.create_subprocess_shell("bluetoothctl default-agent")


# --- Chromecast Listener ---

def on_cast_added(uuid, name):
    logger.info(f"Discovered Cast: {name} ({uuid})")


def on_cast_removed(uuid, name, service):
    logger.info(f"Removed Cast: {name} ({uuid})")
    uuid_str = str(uuid)
    state.chromecasts.pop(uuid_str, None)


# --- App Lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")

    # Create zeroconf instance
    state.zconf = zeroconf.Zeroconf()
    
    # Create browser with SimpleCastListener
    listener = pychromecast.SimpleCastListener(
        add_callback=on_cast_added,
        remove_callback=on_cast_removed
    )
    state.cast_browser = pychromecast.CastBrowser(listener, state.zconf)
    state.cast_browser.start_discovery()

    asyncio.create_task(audio_monitor_loop())
    asyncio.create_task(bluetooth_monitor_loop())  # FIX #6: Monitor BT connection
    task = asyncio.create_task(periodic_update())

    yield

    logger.info("Shutting down...")
    stop_ffmpeg_stream()
    if state.cast_browser:
        state.cast_browser.stop_discovery()
    if state.zconf:
        state.zconf.close()
    task.cancel()


async def bluetooth_monitor_loop():
    """Periodically check Bluetooth connection status."""
    while True:
        state.bt_connected = await get_connected_bluetooth_device()
        await asyncio.sleep(3)


async def periodic_update():
    """Periodically broadcast status to connected clients."""
    while True:
        await broadcast_status()
        await asyncio.sleep(2)


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Endpoints ---

@app.get("/live.mp3")
async def audio_stream():
    # FIX #4: Use async generator
    return StreamingResponse(stream_generator(), media_type="audio/mpeg")


@app.get("/")
async def serve_ui():
    template_path = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if not os.path.exists(template_path):
        template_path = "templates/index.html"
    with open(template_path, "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/api/scan-bt")
async def api_scan_bt():
    await set_discoverable()
    devs = await scan_bluetooth_devices()
    return {"status": "scanning", "devices": devs}


@app.get("/api/pair-mode")
async def api_pair_mode():
    await set_discoverable()
    return {"status": "discoverable", "message": "Device is now discoverable and pairable."}


@app.post("/api/bt/pair/{mac}")
async def api_pair_bt(mac: str):
    """Pair with a specific Bluetooth device by MAC address."""
    # Validate MAC format
    if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', mac):
        raise HTTPException(status_code=400, detail="Invalid MAC address format")
    
    try:
        # First, try to pair
        logger.info(f"Attempting to pair with {mac}")
        pair_proc = await asyncio.create_subprocess_shell(
            f"bluetoothctl pair {mac}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(pair_proc.communicate(), timeout=30)
        pair_output = stdout.decode() + stderr.decode()
        
        # Check if already paired or pairing succeeded
        if "already exists" in pair_output.lower() or "pairing successful" in pair_output.lower() or pair_proc.returncode == 0:
            # Trust the device
            await asyncio.create_subprocess_shell(f"bluetoothctl trust {mac}")
            
            # Now connect
            logger.info(f"Attempting to connect to {mac}")
            connect_proc = await asyncio.create_subprocess_shell(
                f"bluetoothctl connect {mac}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            conn_stdout, conn_stderr = await asyncio.wait_for(connect_proc.communicate(), timeout=30)
            connect_output = conn_stdout.decode() + conn_stderr.decode()
            
            if "successful" in connect_output.lower() or connect_proc.returncode == 0:
                return {"status": "connected", "mac": mac, "message": "Successfully paired and connected"}
            else:
                return {"status": "paired", "mac": mac, "message": "Paired but connection may require action on the device", "details": connect_output}
        else:
            return {"status": "failed", "mac": mac, "message": "Pairing failed", "details": pair_output}
            
    except asyncio.TimeoutError:
        return {"status": "timeout", "mac": mac, "message": "Pairing timed out - device may need to be in pairing mode"}
    except Exception as e:
        logger.error(f"Error pairing with {mac}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bt/connect/{mac}")
async def api_connect_bt(mac: str):
    """Connect to an already-paired Bluetooth device."""
    if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', mac):
        raise HTTPException(status_code=400, detail="Invalid MAC address format")
    
    try:
        proc = await asyncio.create_subprocess_shell(
            f"bluetoothctl connect {mac}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode() + stderr.decode()
        
        if "successful" in output.lower() or proc.returncode == 0:
            return {"status": "connected", "mac": mac}
        else:
            return {"status": "failed", "mac": mac, "details": output}
    except asyncio.TimeoutError:
        return {"status": "timeout", "mac": mac, "message": "Connection timed out"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bt/disconnect/{mac}")
async def api_disconnect_bt(mac: str):
    """Disconnect a Bluetooth device."""
    if not re.match(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$', mac):
        raise HTTPException(status_code=400, detail="Invalid MAC address format")
    
    try:
        proc = await asyncio.create_subprocess_shell(
            f"bluetoothctl disconnect {mac}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return {"status": "disconnected", "mac": mac}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# FIX #2: Add missing audio-sources endpoint
@app.get("/api/audio-sources")
async def api_audio_sources():
    """Return available audio sources for debugging."""
    try:
        # Get PulseAudio/PipeWire sources (short format for quick view)
        proc_short = await asyncio.create_subprocess_shell(
            "pactl list sources short",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_short, _ = await proc_short.communicate()
        sources_short = stdout_short.decode().strip().split('\n')
        
        # Get PulseAudio/PipeWire sources (detailed)
        proc = await asyncio.create_subprocess_shell(
            "pactl list sources",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        sources = []
        current_source = {}
        
        for line in stdout.decode().splitlines():
            line = line.strip()
            if line.startswith("Source #"):
                if current_source:
                    sources.append(current_source)
                current_source = {"id": line}
            elif line.startswith("Name:"):
                current_source["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                current_source["description"] = line.split(":", 1)[1].strip()
            elif line.startswith("State:"):
                current_source["state"] = line.split(":", 1)[1].strip()
        
        if current_source:
            sources.append(current_source)
        
        # Get default source
        proc_default = await asyncio.create_subprocess_shell(
            "pactl get-default-source",
            stdout=asyncio.subprocess.PIPE
        )
        default_stdout, _ = await proc_default.communicate()
        default_source = default_stdout.decode().strip()
        
        # Get sinks too (for monitor sources)
        proc_sinks = await asyncio.create_subprocess_shell(
            "pactl list sinks short",
            stdout=asyncio.subprocess.PIPE
        )
        sinks_stdout, _ = await proc_sinks.communicate()
        sinks_short = sinks_stdout.decode().strip().split('\n')
        
        # Check FFmpeg process status
        ffmpeg_status = "not running"
        if state.ffmpeg_process:
            poll = state.ffmpeg_process.poll()
            if poll is None:
                ffmpeg_status = f"running (PID: {state.ffmpeg_process.pid})"
            else:
                ffmpeg_status = f"exited with code {poll}"
        
        return {
            "sources_short": sources_short,
            "sources_detailed": sources,
            "sinks_short": sinks_short,
            "default_source": default_source,
            "bt_connected": state.bt_connected,
            "current_audio_source": state.current_audio_source,
            "ffmpeg_status": ffmpeg_status,
            "is_streaming": state.is_streaming
        }
    except Exception as e:
        logger.error(f"Error in audio-sources endpoint: {e}")
        return {"error": str(e)}


@app.get("/api/debug/restart-stream")
async def api_restart_stream():
    """Force restart the audio stream - useful for debugging."""
    try:
        logger.info("Force restarting audio stream")
        stop_ffmpeg_stream()
        await asyncio.sleep(1)
        start_ffmpeg_stream()
        return {
            "status": "restarted",
            "audio_source": state.current_audio_source,
            "ffmpeg_running": state.ffmpeg_process is not None
        }
    except Exception as e:
        logger.error(f"Error restarting stream: {e}")
        return {"error": str(e)}


@app.get("/api/debug/set-source/{source_name:path}")
async def api_set_source(source_name: str):
    """Manually set the audio source and restart stream."""
    try:
        logger.info(f"Manually setting audio source to: {source_name}")
        stop_ffmpeg_stream()
        await asyncio.sleep(0.5)
        
        # Manually start FFmpeg with specified source
        cmd = [
            "ffmpeg",
            "-f", "pulse",
            "-i", source_name,
            "-ac", "2",
            "-ar", "44100",
            "-b:a", "192k",
            "-f", "mp3",
            "-fflags", "+nobuffer",
            "-flags", "+low_delay",
            "pipe:1"
        ]
        
        state.ffmpeg_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=4096
        )
        state.is_streaming = True
        state.current_audio_source = source_name
        
        return {
            "status": "started",
            "audio_source": source_name,
            "ffmpeg_pid": state.ffmpeg_process.pid
        }
    except Exception as e:
        logger.error(f"Error setting source: {e}")
        return {"error": str(e)}


@app.get("/api/debug/bluetooth-audio")
async def api_bluetooth_audio_debug():
    """Comprehensive Bluetooth audio diagnostics."""
    results = {}
    
    # 1. Check bluetoothctl for connected devices
    try:
        proc = await asyncio.create_subprocess_shell(
            "bluetoothctl devices Connected",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        results["bt_connected_devices"] = stdout.decode().strip().split('\n') if stdout.decode().strip() else []
    except Exception as e:
        results["bt_connected_devices_error"] = str(e)
    
    # 2. Check bluetoothctl info for the first connected device
    try:
        proc = await asyncio.create_subprocess_shell(
            "bluetoothctl info 2>/dev/null || echo 'No device'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        results["bt_device_info"] = stdout.decode().strip()
    except Exception as e:
        results["bt_device_info_error"] = str(e)
    
    # 3. Check for Bluetooth modules in PulseAudio/PipeWire
    try:
        proc = await asyncio.create_subprocess_shell(
            "pactl list modules short | grep -i blue || echo 'No Bluetooth modules'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        results["pulse_bluetooth_modules"] = stdout.decode().strip()
    except Exception as e:
        results["pulse_bluetooth_modules_error"] = str(e)
    
    # 4. Check WirePlumber status
    try:
        proc = await asyncio.create_subprocess_shell(
            "wpctl status 2>/dev/null || echo 'wpctl not available'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        results["wireplumber_status"] = stdout.decode().strip()
    except Exception as e:
        results["wireplumber_status_error"] = str(e)
    
    # 5. Check PipeWire status
    try:
        proc = await asyncio.create_subprocess_shell(
            "systemctl --user status pipewire --no-pager 2>&1 | head -20 || echo 'Cannot check pipewire status'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        results["pipewire_status"] = stdout.decode().strip()
    except Exception as e:
        results["pipewire_status_error"] = str(e)
    
    # 6. Check for any bluez entries in PipeWire
    try:
        proc = await asyncio.create_subprocess_shell(
            "pw-cli list-objects 2>/dev/null | grep -i blue || echo 'No bluez objects in PipeWire'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        results["pipewire_bluetooth_objects"] = stdout.decode().strip()
    except Exception as e:
        results["pipewire_bluetooth_objects_error"] = str(e)
    
    # 7. Check dbus for Bluetooth audio
    try:
        proc = await asyncio.create_subprocess_shell(
            "dbus-send --system --dest=org.bluez --print-reply / org.freedesktop.DBus.ObjectManager.GetManagedObjects 2>/dev/null | grep -i 'audio\\|a2dp' | head -10 || echo 'No audio profiles found'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        results["bluez_audio_profiles"] = stdout.decode().strip()
    except Exception as e:
        results["bluez_audio_profiles_error"] = str(e)
    
    # 8. Suggest fix
    results["suggestions"] = [
        "If no Bluetooth modules in PulseAudio: Try 'pactl load-module module-bluez5-discover'",
        "If PipeWire not running as user: Check 'systemctl --user status pipewire'",
        "If device connected but no audio source: Try disconnecting and reconnecting the Bluetooth device",
        "Ensure the Bluetooth device is in A2DP mode (audio mode, not HFP/HSP)"
    ]
    
    return results


@app.post("/api/cast/select/{uuid:path}")
async def select_cast(uuid: str):
    """Select and start casting to a Chromecast device."""
    logger.info(f"Received cast select request for UUID: {uuid}")
    
    # Find cast_info from browser devices
    cast_info = None
    for dev_uuid, info in state.cast_browser.devices.items():
        if str(dev_uuid) == uuid:
            cast_info = info
            break
    
    if not cast_info:
        logger.error(f"Chromecast not found for UUID: {uuid}")
        logger.info(f"Available devices: {[str(u) for u in state.cast_browser.devices.keys()]}")
        raise HTTPException(status_code=404, detail="Chromecast not found")

    state.selected_cast_uuid = uuid
    
    # Get or create chromecast connection - run blocking operations in thread
    try:
        if uuid not in state.chromecasts:
            logger.info(f"Creating new connection to {cast_info.friendly_name}")
            
            # Run blocking pychromecast calls in a thread pool
            cast = await asyncio.to_thread(
                pychromecast.get_chromecast_from_cast_info, 
                cast_info, 
                state.zconf
            )
            
            if cast is None:
                raise HTTPException(status_code=500, detail="Failed to connect to Chromecast")
            
            # Wait for connection in thread
            await asyncio.to_thread(cast.wait, 10)
            state.chromecasts[uuid] = cast
        else:
            cast = state.chromecasts[uuid]

        local_ip = get_local_ip()
        stream_url = f"http://{local_ip}:{PORT}{STREAM_ENDPOINT}"

        logger.info(f"Casting {stream_url} to {cast_info.friendly_name}")

        mc = cast.media_controller
        
        # Run blocking media control in thread - use simpler call signature
        def start_media():
            mc.play_media(stream_url, 'audio/mp3', title="Vinyl Stream")
            mc.block_until_active(timeout=15)
        
        await asyncio.to_thread(start_media)
        
        return {"status": "casting", "target": cast_info.friendly_name}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting media playback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start playback: {str(e)}")


@app.post("/api/cast/stop")
async def stop_cast():
    if state.selected_cast_uuid and state.selected_cast_uuid in state.chromecasts:
        try:
            cast = state.chromecasts[state.selected_cast_uuid]
            cast.quit_app()
        except Exception as e:
            logger.error(f"Error stopping cast: {e}")
    state.selected_cast_uuid = None
    stop_ffmpeg_stream()  # Also stop the stream when casting stops
    return {"status": "stopped"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.active_connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in state.active_connections:
            state.active_connections.remove(websocket)


if __name__ == "__main__":
    import uvicorn

    if not os.path.exists("templates"):
        os.makedirs("templates")

    uvicorn.run(app, host="0.0.0.0", port=PORT)
