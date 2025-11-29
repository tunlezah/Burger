# 🎵 Vinyl Streamer Bridge

> *Stream your vinyl records to any Chromecast device in your home!*

![Vinyl to Chromecast](https://img.shields.io/badge/Vinyl-to%20Chromecast-blue?style=for-the-badge&logo=google-chrome)
![PipeWire](https://img.shields.io/badge/Audio-PipeWire-green?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-FastAPI-yellow?style=for-the-badge&logo=python)

---

## 🎯 What Is This?

**Vinyl Streamer Bridge** is a Raspberry Pi (or Linux) based solution that captures audio from a **Bluetooth-enabled turntable** and streams it to any **Google Chromecast** device on your network.

Perfect for:
- 🎸 Listening to your vinyl collection on speakers throughout your home
- 🏠 Multi-room audio from your turntable
- 📻 Bringing analog warmth to modern streaming speakers
- 🎧 Playing records without being tethered to a single room

---

## 🔄 How It Works

```
┌─────────────────┐     Bluetooth      ┌─────────────────┐     WiFi/Stream     ┌─────────────────┐
│                 │    ───────────►    │                 │    ───────────►     │                 │
│   🎵 Turntable  │                    │  🍓 Raspberry   │                     │  📺 Chromecast  │
│   (Bluetooth)   │                    │      Pi         │                     │    Speaker      │
│                 │    ◄───────────    │                 │    ◄───────────     │                 │
└─────────────────┘                    └─────────────────┘                     └─────────────────┘
                                              │
                                              │  Web UI
                                              ▼
                                       ┌─────────────────┐
                                       │  💻 Your Phone  │
                                       │   or Computer   │
                                       └─────────────────┘
```

### The Technical Flow

1. **📡 Bluetooth Reception** - Your turntable (like the Audio-Technica AT-SB727) connects via Bluetooth to the Pi
2. **🎚️ PipeWire Capture** - PipeWire/WirePlumber manages the Bluetooth audio and makes it available as an audio source
3. **🔊 FFmpeg Encoding** - FFmpeg captures the audio and encodes it to MP3 in real-time
4. **🌐 HTTP Streaming** - The encoded audio is served as an HTTP stream
5. **📺 Chromecast Playback** - Chromecast devices fetch and play the stream

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎛️ **Web Control Panel** | Beautiful, responsive web UI to control everything |
| 🔍 **Auto-Discovery** | Automatically finds all Chromecast devices on your network |
| 📱 **Bluetooth Management** | Scan, pair, and connect Bluetooth devices from the web UI |
| 🔄 **Real-time Status** | WebSocket-powered live updates of connection status |
| 🛠️ **Debug Tools** | Built-in diagnostics to troubleshoot audio issues |
| 🎵 **Low Latency** | Optimized FFmpeg settings for minimal delay |
| 🔌 **Auto-Reconnect** | Handles Bluetooth disconnections gracefully |

---

## 📦 What's Included

| File | Purpose |
|------|---------|
| `server.py` | 🐍 FastAPI backend - handles Bluetooth, audio streaming, Chromecast control |
| `index.html` | 🌐 Self-contained web interface - no external dependencies needed |
| `install.sh` | 🔧 Automated setup script - installs everything you need |
| `troubleshoot.sh` | 🩺 Diagnostic script - helps fix common issues |

---

## 🚀 Quick Start

### Prerequisites

- 🍓 Raspberry Pi 4 (or any Linux machine with Bluetooth)
- 📻 Bluetooth-enabled turntable (tested with Audio-Technica AT-SB727)
- 📺 Google Chromecast, Chromecast Audio, or Chromecast-enabled speaker
- 🌐 All devices on the same WiFi network

### Installation

```bash
# 1️⃣ Clone or download the files to your Pi
cd /opt
sudo mkdir vinyl-streamer
sudo chown $USER:$USER vinyl-streamer
cd vinyl-streamer

# 2️⃣ Copy server.py, index.html, and install.sh to this directory

# 3️⃣ Run the installer
chmod +x install.sh
sudo ./install.sh

# 4️⃣ Access the web UI
# Open http://YOUR_PI_IP:8000 in a browser
```

### First-Time Setup

1. **🔵 Pair Your Turntable**
   - Put your turntable in Bluetooth pairing mode
   - Click "Scan for Devices" in the web UI
   - Click on your turntable to pair and connect

2. **📺 Select a Chromecast**
   - Your Chromecasts should appear automatically
   - Click one to select it as the output

3. **▶️ Start Streaming**
   - Click "Start Streaming"
   - Drop the needle on a record
   - Enjoy! 🎶

---

## 🖥️ Web Interface

The web interface provides everything you need:

### Main Controls
```
┌────────────────────────────────────────────────────┐
│  🎵 Vinyl Streamer Bridge                          │
├────────────────────────────────────────────────────┤
│                                                    │
│  Bluetooth: 🟢 Connected - AT-SB727               │
│  Chromecast: 🟢 Living Room Speaker               │
│  Stream: 🟢 Active                                │
│                                                    │
│  [ ▶️ Start Streaming ]  [ ⏹️ Stop Streaming ]     │
│                                                    │
├────────────────────────────────────────────────────┤
│  📡 Bluetooth Devices                              │
│  ┌──────────────────────────────────────────────┐ │
│  │ AT-SB727           Connected    [Disconnect] │ │
│  │ iPhone             Paired       [Connect]    │ │
│  └──────────────────────────────────────────────┘ │
│                        [ 🔍 Scan for Devices ]     │
│                                                    │
├────────────────────────────────────────────────────┤
│  📺 Chromecast Devices                             │
│  ┌──────────────────────────────────────────────┐ │
│  │ ● Living Room Speaker                        │ │
│  │ ○ Kitchen Display                            │ │
│  │ ○ Bedroom Mini                               │ │
│  └──────────────────────────────────────────────┘ │
│                        [ 🔄 Refresh Devices ]      │
│                                                    │
├────────────────────────────────────────────────────┤
│  ▶ Debug Info                                      │
│    [Check Audio Sources] [Test Stream] [Restart]  │
└────────────────────────────────────────────────────┘
```

---

## 🔧 Configuration

### Changing the Service User

By default, the service runs as the `vinyl` user. To change this:

1. Edit `install.sh` and change `SERVICE_USER="vinyl"`
2. Re-run the installer

### Audio Quality Settings

Edit `server.py` to adjust FFmpeg settings:

```python
# Current settings (in start_ffmpeg_stream function)
"-b:a", "192k",      # Bitrate: 128k, 192k, 256k, 320k
"-ar", "44100",      # Sample rate: 44100, 48000
"-ac", "2",          # Channels: 2 (stereo)
```

### Network Port

The default port is **8000**. To change it, edit the uvicorn command in `server.py`:

```python
uvicorn.run(app, host="0.0.0.0", port=8000)  # Change 8000 to your preferred port
```

---

## 🩺 Troubleshooting

### Run the Diagnostic Script

```bash
./troubleshoot.sh
```

This will check:
- ✅ Service user configuration
- ✅ Competing audio servers
- ✅ PipeWire/Bluetooth setup
- ✅ Bluetooth device connections
- ✅ Audio source availability
- ✅ Service status

### Common Issues

#### 🔇 No Audio Playing

1. **Check if Bluetooth source is detected:**
   - Open Debug section in web UI
   - Click "Check Audio Sources"
   - Look for a `bluez_source` or `bluez_input` entry

2. **Multiple audio servers competing:**
   ```bash
   ./troubleshoot.sh --fix-competing
   ```

3. **Bluetooth device disconnected:**
   - Put turntable in pairing mode
   - Click "Scan for Devices" and reconnect

#### 🔵 Bluetooth Won't Connect

1. **Remove and re-pair:**
   ```bash
   bluetoothctl remove XX:XX:XX:XX:XX:XX
   bluetoothctl scan on
   # Put device in pairing mode
   bluetoothctl pair XX:XX:XX:XX:XX:XX
   bluetoothctl trust XX:XX:XX:XX:XX:XX
   bluetoothctl connect XX:XX:XX:XX:XX:XX
   ```

2. **Check for competing WirePlumber instances:**
   ```bash
   pgrep -a wireplumber
   # Should only show one instance owned by 'vinyl' user
   ```

#### 📺 Chromecast Not Found

1. **Ensure same network:** Pi and Chromecast must be on same WiFi
2. **Check multicast:** Some routers block mDNS - enable multicast/IGMP
3. **Firewall:** Allow UDP ports 1900, 5353 and TCP 8008-8009

#### 🔄 Stream Starts But No Sound

1. **Check the audio source in debug:**
   - Click "Check Audio Sources"
   - Note the Bluetooth source name
   - Enter it in "Manual source override"
   - Click "Set Source"

2. **Test stream locally:**
   - Click "Test Stream in Browser"
   - You should hear audio (may be delayed)

---

## 📁 File Structure

```
/opt/vinyl-streamer/
├── server.py           # Main application
├── index.html          # Web interface
├── install.sh          # Installation script
├── troubleshoot.sh     # Diagnostic tool
├── venv/               # Python virtual environment
└── logs/               # Log files (if configured)
```

---

## 🛠️ Technical Details

### Dependencies

| Package | Purpose |
|---------|---------|
| **Python 3.10+** | Runtime |
| **FastAPI** | Web framework |
| **uvicorn** | ASGI server |
| **pychromecast** | Chromecast control |
| **PipeWire** | Audio server |
| **WirePlumber** | PipeWire session manager |
| **FFmpeg** | Audio encoding |
| **BlueZ** | Bluetooth stack |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web interface |
| `/api/status` | GET | Current system status |
| `/api/stream` | GET | Audio stream (MP3) |
| `/api/bt/scan` | POST | Scan for Bluetooth devices |
| `/api/bt/connect/{mac}` | POST | Connect to Bluetooth device |
| `/api/bt/disconnect/{mac}` | POST | Disconnect Bluetooth device |
| `/api/chromecasts` | GET | List Chromecast devices |
| `/api/chromecast/select/{uuid}` | POST | Select Chromecast |
| `/api/streaming/start` | POST | Start streaming |
| `/api/streaming/stop` | POST | Stop streaming |
| `/api/audio-sources` | GET | List audio sources |
| `/api/debug/bluetooth-audio` | GET | Bluetooth diagnostics |
| `/ws` | WebSocket | Real-time status updates |

---

## 🤝 Contributing

Found a bug? Have an idea? Contributions are welcome!

1. 🍴 Fork the repository
2. 🌿 Create a feature branch
3. 💾 Commit your changes
4. 📤 Push to the branch
5. 🎉 Open a Pull Request

---

## 📜 License

This project is open source and available under the [MIT License](LICENSE).

---

## 🙏 Acknowledgments

- 🎵 **Audio-Technica** for making Bluetooth turntables
- 🔊 **PipeWire** team for the amazing audio infrastructure
- 📺 **pychromecast** developers for Chromecast control
- 🐍 **FastAPI** for the excellent web framework

---

## 💬 Support

Having issues? 

1. 📖 Check the [Troubleshooting](#-troubleshooting) section
2. 🩺 Run `./troubleshoot.sh` for automated diagnostics
3. 🐛 Open an issue with the diagnostic output

---

<div align="center">

**Made with ❤️ for vinyl lovers everywhere**

🎵 *Keep the records spinning!* 🎵

</div>
