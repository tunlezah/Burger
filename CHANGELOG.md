# Changelog

All notable changes to Burger - Audio Bridge will be documented in this file.

## [2.0.0] - 2025-11-29

### Added
- **Version Management**: Added version.py module with version tracking (v2.0.0)
- **Configuration System**:
  - config.json file for all settings (audio, server, Bluetooth, Chromecast, fallback)
  - config_manager.py module for managing configuration
  - API endpoints for viewing and updating configuration (`/api/config`, `/api/config/reload`)
- **Enhanced Status Reporting**:
  - Audio source name display
  - Stream bitrate and sample rate information
  - Stream duration tracking
  - Connection history tracking (last 50 events)
  - Error log with timestamps (last 100 errors)
- **New Control Endpoints**:
  - `/api/stream/start` - Manually start audio stream
  - `/api/stream/stop` - Stop audio stream
  - `/api/stream/restart` - Restart stream with retry logic
  - `/api/bluetooth/reconnect` - Reconnect to Bluetooth audio source
  - `/api/errors` - View error log
  - `/api/errors/clear` - Clear error log
  - `/api/status/full` - Get comprehensive system status
  - `/api/version` - Get version information
- **Improved Web UI**:
  - Version display in header
  - Stream information panel (audio source, bitrate, sample rate, duration)
  - Control buttons for stream management (restart, stop, reconnect)
  - Error banner for user-friendly error messages
  - Connection history viewer
  - Enhanced status indicators
  - Better visual design with cards and sections
- **Error Handling & Recovery**:
  - Graceful error handling throughout the application
  - User-friendly error messages with context
  - Automatic retry logic for stream restarts (configurable)
  - Connection event logging
  - Bluetooth reconnection handling
  - Stream failure detection and recovery
- **Fallback Behavior**:
  - Configurable fallback to default audio source
  - Retry logic with exponential backoff
  - Max retries and retry delay configurable

### Changed
- Replaced hardcoded configuration values with config file system
- Enhanced FFmpeg stream startup with configuration-based settings
- Improved Bluetooth pairing with better error reporting
- Updated SystemState class with enhanced tracking capabilities
- WebSocket status now includes additional information (bitrate, sample rate, etc.)

### Improved
- More detailed logging for connection events
- Better error tracking and reporting
- Cleaner separation of configuration from code
- More responsive and informative UI
- Better status visibility for debugging

### Technical Details
- All configuration now centralized in config.json
- Version increments should be tracked in version.py
- Connection history and error logs maintained in-memory with size limits
- Configuration can be updated via API or by editing config.json file
