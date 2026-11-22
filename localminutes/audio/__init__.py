"""Dual-channel Windows WASAPI audio device discovery and capture."""

from localminutes.audio.capture import DualAudioCapture, resample_to_16k_mono
from localminutes.audio.devices import (
    get_default_loopback_device,
    get_default_mic_device,
    list_audio_devices,
)

__all__ = [
    "DualAudioCapture",
    "get_default_loopback_device",
    "get_default_mic_device",
    "list_audio_devices",
    "resample_to_16k_mono",
]
