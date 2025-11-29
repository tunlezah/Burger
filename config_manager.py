"""
Configuration Management Module
Handles loading, saving, and accessing application configuration
"""

import json
import os
import logging
from typing import Any, Dict

logger = logging.getLogger("AudioBridge.Config")

DEFAULT_CONFIG_PATH = "config.json"

# Default configuration in case file doesn't exist
DEFAULT_CONFIG = {
    "server": {
        "host": "0.0.0.0",
        "port": 8000,
        "stream_endpoint": "/live.mp3"
    },
    "audio": {
        "bitrate": "192k",
        "sample_rate": 44100,
        "channels": 2,
        "format": "mp3",
        "buffer_size": 4096
    },
    "chromecast": {
        "auto_discover": True,
        "discovery_timeout": 10,
        "default_device": None,
        "reconnect_on_failure": True,
        "reconnect_delay": 5
    },
    "bluetooth": {
        "auto_reconnect": True,
        "reconnect_interval": 10,
        "scan_timeout": 15,
        "preferred_source": None
    },
    "streaming": {
        "auto_start": False,
        "enable_rms_meter": True,
        "status_update_interval": 2
    },
    "fallback": {
        "use_default_audio_source": True,
        "retry_on_stream_failure": True,
        "max_retries": 3,
        "retry_delay": 5
    }
}


class ConfigManager:
    """Manages application configuration."""

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from file, or use defaults if file doesn't exist."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                logger.info(f"Configuration loaded from {self.config_path}")
                # Merge with defaults to ensure all keys exist
                return self._merge_configs(DEFAULT_CONFIG, config)
            except Exception as e:
                logger.error(f"Error loading config from {self.config_path}: {e}")
                logger.info("Using default configuration")
                return DEFAULT_CONFIG.copy()
        else:
            logger.warning(f"Config file not found at {self.config_path}, using defaults")
            # Create default config file
            self.save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()

    def save_config(self, config: Dict[str, Any] = None) -> bool:
        """Save configuration to file."""
        if config is None:
            config = self.config

        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info(f"Configuration saved to {self.config_path}")
            self.config = config
            return True
        except Exception as e:
            logger.error(f"Error saving config to {self.config_path}: {e}")
            return False

    def get(self, *keys, default=None) -> Any:
        """
        Get a configuration value using dot notation.
        Example: config.get('server', 'port') returns config['server']['port']
        """
        value = self.config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def set(self, *keys, value) -> bool:
        """
        Set a configuration value using dot notation.
        Example: config.set('server', 'port', value=9000)
        """
        if len(keys) == 0:
            return False

        # Navigate to the parent dict
        current = self.config
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        # Set the value
        current[keys[-1]] = value
        return True

    def update(self, updates: Dict[str, Any]) -> bool:
        """Update multiple configuration values at once."""
        try:
            self.config = self._merge_configs(self.config, updates)
            return True
        except Exception as e:
            logger.error(f"Error updating config: {e}")
            return False

    def _merge_configs(self, base: Dict, updates: Dict) -> Dict:
        """Recursively merge two configuration dictionaries."""
        result = base.copy()
        for key, value in updates.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def get_all(self) -> Dict[str, Any]:
        """Get the entire configuration."""
        return self.config.copy()

    def reload(self) -> Dict[str, Any]:
        """Reload configuration from file."""
        self.config = self.load_config()
        return self.config


# Global configuration instance
config = ConfigManager()
