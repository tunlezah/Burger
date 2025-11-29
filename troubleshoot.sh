#!/bin/bash

#===============================================================================
# Vinyl Streamer Bridge - Troubleshooting Script
# 
# This script diagnoses and helps fix common issues with the Bluetooth to
# Chromecast audio streaming setup.
#===============================================================================

set -o pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Symbols
CHECK="✓"
CROSS="✗"
WARN="⚠"
INFO="ℹ"
ARROW="→"

# Service user (change if different)
SERVICE_USER="vinyl"

#-------------------------------------------------------------------------------
# Helper Functions
#-------------------------------------------------------------------------------

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
}

print_section() {
    echo ""
    echo -e "${CYAN}─── $1 ───${NC}"
}

print_ok() {
    echo -e "  ${GREEN}${CHECK}${NC} $1"
}

print_fail() {
    echo -e "  ${RED}${CROSS}${NC} $1"
}

print_warn() {
    echo -e "  ${YELLOW}${WARN}${NC} $1"
}

print_info() {
    echo -e "  ${INFO} $1"
}

print_action() {
    echo -e "  ${YELLOW}${ARROW}${NC} $1"
}

get_service_user_id() {
    id -u "$SERVICE_USER" 2>/dev/null
}

run_as_service_user() {
    local uid=$(get_service_user_id)
    if [ -n "$uid" ]; then
        sudo -u "$SERVICE_USER" XDG_RUNTIME_DIR=/run/user/$uid "$@" 2>/dev/null
    else
        echo "Service user $SERVICE_USER not found"
        return 1
    fi
}

#-------------------------------------------------------------------------------
# Check Functions
#-------------------------------------------------------------------------------

check_service_user() {
    print_section "Service User Check"
    
    if id "$SERVICE_USER" &>/dev/null; then
        print_ok "Service user '$SERVICE_USER' exists"
        
        # Check groups
        local groups=$(groups "$SERVICE_USER" 2>/dev/null)
        if echo "$groups" | grep -q "audio"; then
            print_ok "User is in 'audio' group"
        else
            print_fail "User is NOT in 'audio' group"
            print_action "Fix: sudo usermod -aG audio $SERVICE_USER"
        fi
        
        if echo "$groups" | grep -q "bluetooth"; then
            print_ok "User is in 'bluetooth' group"
        else
            print_fail "User is NOT in 'bluetooth' group"
            print_action "Fix: sudo usermod -aG bluetooth $SERVICE_USER"
        fi
    else
        print_fail "Service user '$SERVICE_USER' does not exist"
        print_action "Fix: sudo useradd -r -s /bin/false -G audio,bluetooth $SERVICE_USER"
        return 1
    fi
}

check_competing_audio_servers() {
    print_section "Competing Audio Servers Check"
    
    local dominated=0
    local service_uid=$(get_service_user_id)
    
    # Check for multiple WirePlumber instances
    local wp_count=$(pgrep -c wireplumber 2>/dev/null || echo "0")
    local wp_pids=$(pgrep wireplumber 2>/dev/null)
    
    if [ "$wp_count" -gt 1 ]; then
        print_warn "Multiple WirePlumber instances running ($wp_count found)"
        
        # Show who owns each
        for pid in $wp_pids; do
            local owner=$(ps -o user= -p $pid 2>/dev/null)
            local uid=$(id -u "$owner" 2>/dev/null)
            if [ "$owner" != "$SERVICE_USER" ]; then
                print_fail "  PID $pid owned by '$owner' (should only be $SERVICE_USER)"
                dominated=1
            else
                print_ok "  PID $pid owned by '$SERVICE_USER' (correct)"
            fi
        done
        
        if [ $dominated -eq 1 ]; then
            print_action "Fix: Stop other users' audio services:"
            for pid in $wp_pids; do
                local owner=$(ps -o user= -p $pid 2>/dev/null)
                if [ "$owner" != "$SERVICE_USER" ]; then
                    echo "       sudo -u $owner XDG_RUNTIME_DIR=/run/user/$(id -u $owner) systemctl --user stop pipewire wireplumber"
                fi
            done
        fi
    elif [ "$wp_count" -eq 1 ]; then
        local owner=$(ps -o user= -p $wp_pids 2>/dev/null)
        if [ "$owner" = "$SERVICE_USER" ]; then
            print_ok "Single WirePlumber instance running (owned by $SERVICE_USER)"
        else
            print_fail "WirePlumber running but owned by '$owner', not '$SERVICE_USER'"
            dominated=1
        fi
    else
        print_warn "No WirePlumber running"
        print_action "Fix: sudo -u $SERVICE_USER XDG_RUNTIME_DIR=/run/user/$service_uid systemctl --user start wireplumber"
    fi
    
    # Check for PulseAudio (should be masked when using PipeWire)
    if pgrep -x pulseaudio &>/dev/null; then
        print_warn "PulseAudio is running (may conflict with PipeWire)"
        print_action "Fix: systemctl --user stop pulseaudio; systemctl --user mask pulseaudio"
    else
        print_ok "PulseAudio not running"
    fi
    
    # Check for bluealsa
    if pgrep bluealsa &>/dev/null; then
        print_fail "bluealsa is running (will conflict with PipeWire Bluetooth)"
        print_action "Fix: sudo systemctl stop bluealsa; sudo systemctl disable bluealsa"
        dominated=1
    else
        print_ok "bluealsa not running"
    fi
    
    return $dominated
}

check_pipewire_bluetooth() {
    print_section "PipeWire Bluetooth Support Check"
    
    # Check if bluetooth SPA plugin exists
    local spa_path="/usr/lib/$(uname -m)-linux-gnu/spa-0.2/bluez5/libspa-bluez5.so"
    # Try alternative path
    if [ ! -f "$spa_path" ]; then
        spa_path=$(find /usr/lib -name "libspa-bluez5.so" 2>/dev/null | head -1)
    fi
    
    if [ -n "$spa_path" ] && [ -f "$spa_path" ]; then
        print_ok "PipeWire Bluetooth plugin found: $spa_path"
    else
        print_fail "PipeWire Bluetooth plugin NOT found"
        print_action "Fix: sudo apt install libspa-0.2-bluetooth pipewire-audio-client-libraries"
        return 1
    fi
    
    # Check WirePlumber bluetooth config
    if [ -d "/usr/share/wireplumber/bluetooth.lua.d" ]; then
        print_ok "WirePlumber Bluetooth config directory exists"
    else
        print_fail "WirePlumber Bluetooth config directory missing"
    fi
    
    # Check for logind override (needed for lingering sessions)
    local logind_override="/home/$SERVICE_USER/.config/wireplumber/bluetooth.lua.d/51-disable-logind.lua"
    if [ -f "$logind_override" ]; then
        print_ok "Logind override config exists (needed for service users)"
    else
        print_warn "Logind override config missing"
        print_action "Fix: Create $logind_override with:"
        echo '       bluez_monitor.properties["with-logind"] = false'
    fi
}

check_bluetooth_status() {
    print_section "Bluetooth Status Check"
    
    # Check if bluetoothd is running
    if systemctl is-active --quiet bluetooth; then
        print_ok "Bluetooth service is running"
    else
        print_fail "Bluetooth service is NOT running"
        print_action "Fix: sudo systemctl start bluetooth"
        return 1
    fi
    
    # Check adapter
    local adapter_info=$(bluetoothctl show 2>/dev/null)
    if [ -n "$adapter_info" ]; then
        print_ok "Bluetooth adapter found"
        
        if echo "$adapter_info" | grep -q "Powered: yes"; then
            print_ok "Adapter is powered on"
        else
            print_fail "Adapter is powered OFF"
            print_action "Fix: bluetoothctl power on"
        fi
        
        if echo "$adapter_info" | grep -q "Discoverable: yes"; then
            print_ok "Adapter is discoverable"
        else
            print_warn "Adapter is not discoverable (may be needed for pairing)"
            print_action "Fix: bluetoothctl discoverable on"
        fi
    else
        print_fail "No Bluetooth adapter found"
        return 1
    fi
}

check_bluetooth_device() {
    print_section "Bluetooth Device Check"
    
    # Get list of paired devices
    local devices=$(bluetoothctl devices Paired 2>/dev/null)
    
    if [ -z "$devices" ]; then
        print_warn "No paired Bluetooth devices"
        print_action "To pair: bluetoothctl scan on, then pair <MAC_ADDRESS>"
        return 1
    fi
    
    print_info "Paired devices:"
    echo "$devices" | while read line; do
        echo "       $line"
    done
    
    # Check for connected devices
    local connected=$(bluetoothctl devices Connected 2>/dev/null)
    
    if [ -z "$connected" ]; then
        print_warn "No Bluetooth devices currently connected"
        print_action "To connect: bluetoothctl connect <MAC_ADDRESS>"
        
        # Show paired devices that could be connected
        echo ""
        print_info "Try connecting one of the paired devices above"
    else
        print_ok "Connected device(s):"
        echo "$connected" | while read line; do
            local mac=$(echo "$line" | awk '{print $2}')
            local name=$(echo "$line" | cut -d' ' -f3-)
            echo "       $name ($mac)"
            
            # Check device info
            local info=$(bluetoothctl info "$mac" 2>/dev/null)
            
            if echo "$info" | grep -q "Trusted: yes"; then
                print_ok "  Device is trusted"
            else
                print_warn "  Device is NOT trusted"
                print_action "  Fix: bluetoothctl trust $mac"
            fi
            
            # Check for audio UUIDs
            if echo "$info" | grep -qi "0000110a\|Audio Source"; then
                print_ok "  Device has A2DP Audio Source profile"
            else
                print_warn "  Device may not support A2DP audio source"
            fi
        done
    fi
}

check_pipewire_bluetooth_source() {
    print_section "PipeWire Audio Sources Check"
    
    local sources=$(run_as_service_user pactl list sources short 2>/dev/null)
    
    if [ -z "$sources" ]; then
        print_fail "Cannot query PipeWire sources (is PipeWire running for $SERVICE_USER?)"
        return 1
    fi
    
    print_info "Available audio sources:"
    echo "$sources" | while read line; do
        echo "       $line"
    done
    
    # Check for Bluetooth source
    if echo "$sources" | grep -qi "bluez"; then
        print_ok "Bluetooth audio source detected!"
        local bt_source=$(echo "$sources" | grep -i bluez | awk '{print $2}')
        print_info "Bluetooth source name: $bt_source"
        echo ""
        print_info "Use this source name in the vinyl streamer config or debug UI"
    else
        print_fail "No Bluetooth audio source in PipeWire"
        echo ""
        print_info "This usually means:"
        echo "       1. Bluetooth device is not connected"
        echo "       2. Another WirePlumber grabbed the device"
        echo "       3. WirePlumber hasn't detected the device yet"
        echo ""
        print_action "Try: Disconnect and reconnect the Bluetooth device"
        print_action "Then: sudo -u $SERVICE_USER XDG_RUNTIME_DIR=/run/user/$(get_service_user_id) systemctl --user restart wireplumber"
    fi
}

check_wireplumber_status() {
    print_section "WirePlumber Status Check"
    
    local status=$(run_as_service_user wpctl status 2>/dev/null)
    
    if [ -z "$status" ]; then
        print_fail "Cannot query WirePlumber status"
        return 1
    fi
    
    # Check for Bluetooth device in wpctl status
    if echo "$status" | grep -qi "bluez5"; then
        print_ok "Bluetooth device visible in WirePlumber"
        
        # Extract and show the device
        echo "$status" | grep -i "bluez5" | while read line; do
            print_info "  $line"
        done
    else
        print_warn "No Bluetooth device visible in WirePlumber"
    fi
    
    # Check for streams
    if echo "$status" | grep -qi "bluez_input\|bluez_output"; then
        print_ok "Bluetooth audio stream active"
    else
        print_warn "No active Bluetooth audio stream"
    fi
}

check_vinyl_streamer_service() {
    print_section "Vinyl Streamer Service Check"
    
    if systemctl is-active --quiet vinyl-streamer; then
        print_ok "vinyl-streamer service is running"
    else
        print_warn "vinyl-streamer service is NOT running"
        print_action "Fix: sudo systemctl start vinyl-streamer"
    fi
    
    if systemctl is-enabled --quiet vinyl-streamer 2>/dev/null; then
        print_ok "vinyl-streamer service is enabled (will start on boot)"
    else
        print_warn "vinyl-streamer service is not enabled"
        print_action "Fix: sudo systemctl enable vinyl-streamer"
    fi
    
    # Check if the web server is responding
    if curl -s --connect-timeout 2 http://localhost:8000/api/status &>/dev/null; then
        print_ok "Web API is responding on port 8000"
    else
        print_warn "Web API not responding on port 8000"
    fi
}

check_ffmpeg() {
    print_section "FFmpeg Check"
    
    if command -v ffmpeg &>/dev/null; then
        print_ok "FFmpeg is installed"
        
        # Check if it has pulse support
        if ffmpeg -devices 2>&1 | grep -q pulse; then
            print_ok "FFmpeg has PulseAudio/PipeWire support"
        else
            print_warn "FFmpeg may not have PulseAudio support"
        fi
    else
        print_fail "FFmpeg is NOT installed"
        print_action "Fix: sudo apt install ffmpeg"
    fi
}

#-------------------------------------------------------------------------------
# Fix Functions
#-------------------------------------------------------------------------------

fix_competing_servers() {
    print_header "Fixing Competing Audio Servers"
    
    local service_uid=$(get_service_user_id)
    
    # Kill all wireplumber except vinyl's
    print_action "Stopping competing WirePlumber instances..."
    
    local wp_pids=$(pgrep wireplumber 2>/dev/null)
    for pid in $wp_pids; do
        local owner=$(ps -o user= -p $pid 2>/dev/null)
        if [ "$owner" != "$SERVICE_USER" ]; then
            print_info "Killing WirePlumber PID $pid (owned by $owner)"
            sudo kill $pid 2>/dev/null
        fi
    done
    
    # Also kill their pipewire instances
    local users_to_stop=$(pgrep -a wireplumber 2>/dev/null | grep -v "$SERVICE_USER" | awk '{print $1}' | xargs -I{} ps -o user= -p {} 2>/dev/null | sort -u)
    
    for user in $users_to_stop; do
        if [ "$user" != "$SERVICE_USER" ] && [ -n "$user" ]; then
            print_info "Stopping PipeWire for user $user"
            local uid=$(id -u "$user" 2>/dev/null)
            if [ -n "$uid" ]; then
                sudo pkill -u "$user" pipewire 2>/dev/null
                sudo pkill -u "$user" wireplumber 2>/dev/null
            fi
        fi
    done
    
    sleep 2
    
    # Restart vinyl's services
    print_action "Restarting $SERVICE_USER's PipeWire services..."
    run_as_service_user systemctl --user restart pipewire pipewire-pulse wireplumber
    
    sleep 3
    print_ok "Done"
}

fix_bluetooth_reconnect() {
    print_header "Reconnecting Bluetooth Device"
    
    # Get the first connected or paired device
    local device=$(bluetoothctl devices Paired 2>/dev/null | head -1 | awk '{print $2}')
    
    if [ -z "$device" ]; then
        print_fail "No paired devices to reconnect"
        return 1
    fi
    
    local name=$(bluetoothctl devices Paired 2>/dev/null | head -1 | cut -d' ' -f3-)
    
    print_info "Reconnecting to: $name ($device)"
    
    print_action "Disconnecting..."
    bluetoothctl disconnect "$device" 2>/dev/null
    sleep 2
    
    print_action "Reconnecting..."
    bluetoothctl connect "$device" 2>/dev/null
    sleep 3
    
    # Check if connected
    if bluetoothctl info "$device" 2>/dev/null | grep -q "Connected: yes"; then
        print_ok "Device connected!"
        
        # Restart wireplumber to pick it up
        print_action "Restarting WirePlumber to detect device..."
        run_as_service_user systemctl --user restart wireplumber
        sleep 3
        
        # Check for bluetooth source
        if run_as_service_user pactl list sources short 2>/dev/null | grep -qi bluez; then
            print_ok "Bluetooth audio source now available!"
        else
            print_warn "Bluetooth source not appearing yet"
            print_action "Try: Put device in pairing mode and reconnect"
        fi
    else
        print_fail "Could not reconnect device"
        print_action "Put the device in pairing mode and try: bluetoothctl connect $device"
    fi
}

#-------------------------------------------------------------------------------
# Main
#-------------------------------------------------------------------------------

main() {
    print_header "Vinyl Streamer Bridge - Troubleshooting"
    echo ""
    echo "This script will diagnose common issues with your Bluetooth to"
    echo "Chromecast audio streaming setup."
    echo ""
    echo "Service user: $SERVICE_USER"
    
    # Run all checks
    check_service_user
    check_competing_audio_servers
    check_pipewire_bluetooth
    check_bluetooth_status
    check_bluetooth_device
    check_wireplumber_status
    check_pipewire_bluetooth_source
    check_vinyl_streamer_service
    check_ffmpeg
    
    print_header "Summary & Recommendations"
    
    echo ""
    echo "If you're having issues, try these steps in order:"
    echo ""
    echo "  1. Stop competing audio servers:"
    echo "     $0 --fix-competing"
    echo ""
    echo "  2. Reconnect Bluetooth device:"
    echo "     $0 --fix-bluetooth"
    echo ""
    echo "  3. Restart the vinyl streamer:"
    echo "     sudo systemctl restart vinyl-streamer"
    echo ""
    echo "  4. Check the web UI debug section for audio sources"
    echo ""
    
    print_header "End of Troubleshooting Report"
}

# Parse arguments
case "${1:-}" in
    --fix-competing)
        fix_competing_servers
        ;;
    --fix-bluetooth)
        fix_bluetooth_reconnect
        ;;
    --fix-all)
        fix_competing_servers
        fix_bluetooth_reconnect
        ;;
    --help|-h)
        echo "Vinyl Streamer Bridge Troubleshooting Script"
        echo ""
        echo "Usage: $0 [option]"
        echo ""
        echo "Options:"
        echo "  (no option)      Run full diagnostic report"
        echo "  --fix-competing  Stop competing audio servers"
        echo "  --fix-bluetooth  Reconnect Bluetooth device"
        echo "  --fix-all        Run all fixes"
        echo "  --help           Show this help"
        ;;
    *)
        main
        ;;
esac
