#!/bin/bash
set -e

# --- Configuration ---
APP_DIR="/opt/vinyl-streamer"
USER_NAME="vinyl"
VENV_DIR="$APP_DIR/venv"
SERVICE_NAME="vinyl-streamer"

echo ">>> Starting Vinyl Streamer Installation..."

# 1. Install System Dependencies
echo ">>> Installing dependencies..."
sudo apt-get update
sudo apt-get install -y \
    python3 python3-venv python3-pip git \
    ffmpeg bluez bluez-tools \
    pipewire pipewire-pulse wireplumber \
    dbus-user-session avahi-daemon \
    libglib2.0-dev pulseaudio-utils

# 2. Setup User
if ! id "$USER_NAME" &>/dev/null; then
    echo ">>> Creating system user $USER_NAME..."
    sudo useradd -r -m -s /bin/bash -G audio,bluetooth $USER_NAME
    sudo loginctl enable-linger $USER_NAME
else
    echo ">>> User $USER_NAME exists."
    sudo usermod -a -G audio,bluetooth $USER_NAME
fi

# 3. Setup Directory Structure
echo ">>> Setting up application directory at $APP_DIR..."
sudo mkdir -p $APP_DIR/templates
sudo chown -R $USER_NAME:$USER_NAME $APP_DIR

# Copy files - handle both flat and nested structures
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/server.py" ]; then
    echo ">>> Copying application files..."
    sudo cp "$SCRIPT_DIR/server.py" $APP_DIR/
    
    # Handle index.html - check multiple locations
    if [ -f "$SCRIPT_DIR/templates/index.html" ]; then
        sudo cp "$SCRIPT_DIR/templates/index.html" $APP_DIR/templates/
    elif [ -f "$SCRIPT_DIR/index.html" ]; then
        sudo cp "$SCRIPT_DIR/index.html" $APP_DIR/templates/
    else
        echo "!! WARNING: index.html not found"
    fi
    
    sudo chown -R $USER_NAME:$USER_NAME $APP_DIR
else
    echo "!! WARNING: server.py not found in $SCRIPT_DIR"
    echo "!! Please manually copy application files to $APP_DIR"
fi

# 4. Setup Python Environment
echo ">>> Setting up Python virtual environment..."
sudo -u $USER_NAME bash -c "python3 -m venv $VENV_DIR"
sudo -u $USER_NAME bash -c "$VENV_DIR/bin/pip install --upgrade pip"
sudo -u $USER_NAME bash -c "$VENV_DIR/bin/pip install fastapi uvicorn pychromecast websockets python-multipart zeroconf"

# 5. Configure Bluetooth
echo ">>> Configuring Bluetooth..."
sudo systemctl enable --now bluetooth

# Configure Bluetooth agent for auto-pairing
sudo mkdir -p /etc/bluetooth
sudo tee /etc/bluetooth/main.conf > /dev/null <<EOF
[General]
Class = 0x200414
DiscoverableTimeout = 0
PairableTimeout = 0
Privacy = off
Name = vinyl

[Policy]
AutoEnable=true
EOF

sudo systemctl restart bluetooth

# 6. Configure Firewall
if command -v ufw > /dev/null; then
    if sudo ufw status | grep -q "Status: active"; then
        echo ">>> Firewall detected. Allowing port 8000..."
        sudo ufw allow 8000/tcp
    fi
fi

# 7. Get user ID for service
USER_ID=$(id -u $USER_NAME)

# 8. Ensure runtime directory exists and has correct permissions
echo ">>> Setting up runtime directory..."
sudo mkdir -p /run/user/$USER_ID
sudo chown $USER_NAME:$USER_NAME /run/user/$USER_ID
sudo chmod 700 /run/user/$USER_ID

# 9. Setup PipeWire services for the vinyl user BEFORE creating the main service
echo ">>> Setting up PipeWire for user $USER_NAME..."

# Create user systemd directory
sudo -u $USER_NAME mkdir -p /home/$USER_NAME/.config/systemd/user

# Enable linger to allow user services to run without login
sudo loginctl enable-linger $USER_NAME

# Start a user D-Bus session and enable PipeWire within it
sudo -u $USER_NAME bash -c "
    export XDG_RUNTIME_DIR=/run/user/$USER_ID
    export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$USER_ID/bus
    
    # Start D-Bus session if not running
    if [ ! -S /run/user/$USER_ID/bus ]; then
        dbus-daemon --session --address=\$DBUS_SESSION_BUS_ADDRESS --nofork --nopidfile --syslog-only &
        sleep 1
    fi
    
    systemctl --user daemon-reload
    systemctl --user enable pipewire pipewire-pulse wireplumber
    systemctl --user start pipewire pipewire-pulse wireplumber || true
"

# 10. Configure WirePlumber for Bluetooth audio routing
# FIX #7: Use correct WirePlumber 0.4+ configuration format
echo ">>> Configuring WirePlumber for Bluetooth audio routing..."

# Create WirePlumber config directory
WIREPLUMBER_CONFIG_DIR="/home/$USER_NAME/.config/wireplumber/wireplumber.conf.d"
sudo -u $USER_NAME mkdir -p "$WIREPLUMBER_CONFIG_DIR"

# Modern WirePlumber config for Bluetooth
sudo -u $USER_NAME tee "$WIREPLUMBER_CONFIG_DIR/51-bluetooth-config.conf" > /dev/null <<'EOF'
# Enable Bluetooth audio and set it as preferred when connected
monitor.bluez.properties = {
  bluez5.enable-sbc-xq = true
  bluez5.enable-msbc = true
  bluez5.enable-hw-volume = true
  bluez5.roles = [ a2dp_sink a2dp_source ]
}
EOF

# Create a Lua script for auto-routing (if using older WirePlumber)
WIREPLUMBER_SCRIPTS_DIR="/home/$USER_NAME/.config/wireplumber/scripts"
sudo -u $USER_NAME mkdir -p "$WIREPLUMBER_SCRIPTS_DIR"

sudo -u $USER_NAME tee "$WIREPLUMBER_SCRIPTS_DIR/51-bluetooth-autoconnect.lua" > /dev/null <<'EOF'
-- Auto-connect Bluetooth audio sources when they appear
-- This script runs when new nodes are added

function handle_new_node(node)
  local dominated_name = node.properties["node.name"]
  if dominated_name and string.match(dominated_name, "^bluez") then
    Log.info("Bluetooth node detected: " .. dominated_name)
  end
end
EOF

sudo chown -R $USER_NAME:$USER_NAME /home/$USER_NAME/.config/wireplumber

# 11. Create Systemd Service
echo ">>> Creating Systemd service..."
sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null <<EOF
[Unit]
Description=Vinyl Streamer Bluetooth to Chromecast Bridge
After=network.target sound.target bluetooth.service avahi-daemon.service
Wants=avahi-daemon.service bluetooth.service

[Service]
Type=simple
User=$USER_NAME
Group=$USER_NAME
WorkingDirectory=$APP_DIR

# Environment setup for PipeWire/PulseAudio access
Environment=XDG_RUNTIME_DIR=/run/user/$USER_ID
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$USER_ID/bus
Environment=PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
Environment=PULSE_SERVER=unix:/run/user/$USER_ID/pulse/native

# Ensure PipeWire is running before starting
ExecStartPre=/bin/bash -c 'systemctl --user --machine=$USER_NAME@ is-active pipewire || systemctl --user --machine=$USER_NAME@ start pipewire pipewire-pulse wireplumber'

ExecStart=$VENV_DIR/bin/uvicorn server:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

# Resource limits
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

# 12. Create a helper script for Bluetooth pairing
echo ">>> Creating Bluetooth pairing helper..."
sudo tee $APP_DIR/bt-agent.sh > /dev/null <<'BTEOF'
#!/bin/bash
# Auto-accept Bluetooth pairing requests
bluetoothctl << EOF
power on
discoverable on
pairable on
agent NoInputNoOutput
default-agent
EOF

# Keep the agent running
while true; do
    sleep 60
done
BTEOF

sudo chmod +x $APP_DIR/bt-agent.sh
sudo chown $USER_NAME:$USER_NAME $APP_DIR/bt-agent.sh

# Create a systemd service for the Bluetooth agent
sudo tee /etc/systemd/system/vinyl-bt-agent.service > /dev/null <<EOF
[Unit]
Description=Vinyl Streamer Bluetooth Agent
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
User=root
ExecStart=$APP_DIR/bt-agent.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# 13. Finalize
echo ">>> Reloading systemd and enabling services..."
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl enable vinyl-bt-agent

echo ">>> Starting services..."
sudo systemctl start vinyl-bt-agent
sleep 2
sudo systemctl restart $SERVICE_NAME

sleep 5

if systemctl is-active --quiet $SERVICE_NAME; then
    IP_ADDR=$(hostname -I | awk '{print $1}')
    echo ""
    echo "=========================================="
    echo ">>> SUCCESS: Service is running!"
    echo ">>> Access the UI at: http://$IP_ADDR:8000"
    echo "=========================================="
    echo ""
    echo "NEXT STEPS:"
    echo "1. Pair your phone/turntable via Bluetooth"
    echo "2. The device will appear as 'vinyl' in your Bluetooth settings"
    echo "3. Open the web UI to select your Chromecast"
    echo ""
    echo "TROUBLESHOOTING:"
    echo "- Check service status: sudo systemctl status $SERVICE_NAME"
    echo "- View logs: sudo journalctl -u $SERVICE_NAME -f"
    echo "- Check Bluetooth: bluetoothctl show"
    echo "- Check audio sources: pactl list sources short"
    echo ""
else
    echo ">>> ERROR: Service failed to start."
    echo "---------------------------------------------------------------"
    sudo journalctl -u $SERVICE_NAME --no-pager -n 50
    echo "---------------------------------------------------------------"
    echo ""
    echo "Common fixes:"
    echo "1. Ensure PipeWire is running: systemctl --user status pipewire"
    echo "2. Check Bluetooth: sudo systemctl status bluetooth"
    echo "3. Reboot and try again"
fi
