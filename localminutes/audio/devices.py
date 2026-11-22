"""Windows WASAPI microphone and loopback device enumeration via pyaudiowpatch."""

from __future__ import annotations

from typing import Optional

from localminutes.models import AudioDevice

try:
    import pyaudiowpatch as pyaudio
except ImportError:  # pragma: no cover
    pyaudio = None  # type: ignore[assignment]


def list_audio_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Return (microphones, loopback_devices) available on this Windows machine."""
    if pyaudio is None:
        return [], []

    mics: list[AudioDevice] = []
    loopbacks: list[AudioDevice] = []

    p = pyaudio.PyAudio()
    try:
        try:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            wasapi_idx = int(wasapi_info["index"])
            default_mic_idx = int(wasapi_info.get("defaultInputDevice", -1))
        except OSError:
            wasapi_idx = -1
            default_mic_idx = -1

        try:
            default_loopback = p.get_default_wasapi_loopback()
            default_lb_idx = int(default_loopback["index"])
        except Exception:
            default_lb_idx = -1

        # Enumerate microphones (prefer WASAPI host API to avoid duplicates)
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if int(info.get("maxInputChannels", 0)) <= 0:
                continue
            if info.get("isLoopbackDevice", False):
                continue
            if wasapi_idx != -1 and int(info.get("hostApi", -1)) != wasapi_idx:
                continue
            mics.append(
                AudioDevice(
                    index=int(info["index"]),
                    name=str(info["name"]),
                    is_loopback=False,
                    channels=max(1, int(info["maxInputChannels"])),
                    default_sample_rate=int(info["defaultSampleRate"]),
                    is_default=(int(info["index"]) == default_mic_idx),
                )
            )

        # Enumerate WASAPI loopback devices
        if hasattr(p, "get_loopback_device_info_generator"):
            for info in p.get_loopback_device_info_generator():
                loopbacks.append(
                    AudioDevice(
                        index=int(info["index"]),
                        name=str(info["name"]),
                        is_loopback=True,
                        channels=max(1, int(info["maxInputChannels"])),
                        default_sample_rate=int(info["defaultSampleRate"]),
                        is_default=(int(info["index"]) == default_lb_idx),
                    )
                )
    finally:
        p.terminate()

    return mics, loopbacks


def get_default_mic_device() -> Optional[AudioDevice]:
    mics, _ = list_audio_devices()
    for d in mics:
        if d.is_default:
            return d
    return mics[0] if mics else None


def get_default_loopback_device() -> Optional[AudioDevice]:
    _, lbs = list_audio_devices()
    for d in lbs:
        if d.is_default:
            return d
    return lbs[0] if lbs else None
