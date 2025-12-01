"""
Burger - Bluetooth Audio to Chromecast Bridge
Version Management Module
"""

__version__ = "2.0.3"
__app_name__ = "Burger - Audio Bridge"
__description__ = "Stream Bluetooth audio to any Chromecast device"

def get_version():
    """Returns the current version string."""
    return __version__

def get_version_info():
    """Returns detailed version information."""
    return {
        "version": __version__,
        "app_name": __app_name__,
        "description": __description__
    }
