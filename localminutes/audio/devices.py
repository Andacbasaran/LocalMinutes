"""Cross-platform audio device enumeration for Windows (WASAPI), macOS (CoreAudio), and Linux (PipeWire/PulseAudio)."""

from __future__ import annotations

import sys
from typing import Optional

from localminutes.models import AudioDevice

try:
    import pyaudiowpatch as pyaudio
except Exception:  # pragma: no cover
    pyaudio = None  # type: ignore[assignment]

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - headless CI without PulseAudio/PortAudio server
    sd = None  # type: ignore[assignment]

_MACOS_LOOPBACK_KEYWORDS = (
    "blackhole",
    "loopback audio",
    "loopback",
    "vb-cable",
    "vbcable",
    "soundflower",
    "aggregate",
    "multi-output",
    "existential audio",
    "virtual audio",
)

_LINUX_LOOPBACK_KEYWORDS = (
    ".monitor",
    "monitor of",
    "monitor",
    "loopback",
    "pipewire-monitor",
)


def is_virtual_loopback_name(name: str, platform_name: Optional[str] = None) -> bool:
    """Classify whether an input device name represents a virtual system-audio loopback sink."""
    plat = (platform_name or sys.platform).lower()
    low = (name or "").strip().lower()
    if not low:
        return False
    if plat == "darwin":
        return any(kw in low for kw in _MACOS_LOOPBACK_KEYWORDS)
    if plat.startswith("linux"):
        return any(kw in low for kw in _LINUX_LOOPBACK_KEYWORDS)
    # Windows fallback if using sounddevice instead of pyaudiowpatch
    return any(kw in low for kw in ("stereo mix", "wasapi loopback", "loopback", "vb-cable", "cable output"))


def get_loopback_setup_hint(lang: str = "en", platform_name: Optional[str] = None) -> str:
    """Return concise OS-specific instructions for capturing remote/system meeting audio."""
    plat = (platform_name or sys.platform).lower()
    if plat == "win32":
        if lang == "tr":
            return "Windows WASAPI Loopback hazır — harici sürücü gerekmeden Zoom/Teams/Meet sesini yakalar."
        return "Windows WASAPI Loopback ready — zero-setup capture of Zoom, Teams, Meet & browser audio."
    if plat == "darwin":
        if lang == "tr":
            return (
                "macOS sistem sesi için BlackHole önerilir: Terminalde 'brew install blackhole-2ch' "
                "çalıştırıp Audio MIDI Setup'ta Çoklu Çıkış Aygıtı oluşturun (Mikrofon tek kanal hemen çalışır)."
            )
        return (
            "For macOS system audio, install BlackHole ('brew install blackhole-2ch') and create a "
            "Multi-Output Device in Audio MIDI Setup. Microphone capture works out-of-the-box."
        )
    if lang == "tr":
        return (
            "Linux PipeWire / PulseAudio '.monitor' girişleri otomatik algılanır. "
            "Listede görünmüyorsa pavucontrol üzerinden monitör kaynağını etkinleştirin."
        )
    return (
        "Linux PipeWire / PulseAudio '.monitor' sinks are auto-detected. "
        "Use pavucontrol or qpwgraph if your output monitor needs routing."
    )


def _list_wasapi_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Enumerate Windows WASAPI microphones and native loopback endpoints via pyaudiowpatch."""
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
                    backend="pyaudiowpatch",
                )
            )

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
                        backend="pyaudiowpatch",
                    )
                )
    finally:
        p.terminate()

    return mics, loopbacks


def _list_sounddevice_devices(
    platform_name: Optional[str] = None,
) -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Enumerate microphones and virtual/monitor loopback devices via sounddevice (PortAudio)."""
    if sd is None:
        return [], []

    plat = (platform_name or sys.platform).lower()
    mics: list[AudioDevice] = []
    loopbacks: list[AudioDevice] = []

    try:
        devices = sd.query_devices()
    except Exception:
        return [], []

    default_in_idx = -1
    try:
        def_dev = sd.default.device
        if isinstance(def_dev, (tuple, list)) and len(def_dev) >= 1 and def_dev[0] is not None:
            default_in_idx = int(def_dev[0])
        elif isinstance(def_dev, int):
            default_in_idx = def_dev
    except Exception:
        default_in_idx = -1

    for idx, info in enumerate(devices):
        max_in = int(info.get("max_input_channels", 0) or 0)
        if max_in <= 0:
            continue
        name = str(info.get("name", f"Audio Input {idx}")).strip()
        sr = int(float(info.get("default_samplerate", 48_000) or 48_000))
        is_lb = is_virtual_loopback_name(name, platform_name=plat)
        dev = AudioDevice(
            index=idx,
            name=name,
            is_loopback=is_lb,
            channels=max(1, max_in),
            default_sample_rate=sr,
            is_default=(idx == default_in_idx and not is_lb),
            backend="sounddevice",
        )
        if is_lb:
            loopbacks.append(dev)
        else:
            mics.append(dev)

    if loopbacks and not any(d.is_default for d in loopbacks):
        # Prefer BlackHole 2ch on macOS or first monitor sink on Linux as default loopback
        preferred = next(
            (d for d in loopbacks if "blackhole 2ch" in d.name.lower()),
            loopbacks[0],
        )
        preferred.is_default = True

    if mics and not any(d.is_default for d in mics):
        mics[0].is_default = True

    return mics, loopbacks


def list_audio_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Return `(microphones, loopback_devices)` using the best native backend for this OS."""
    if sys.platform == "win32" and pyaudio is not None:
        mics, loopbacks = _list_wasapi_devices()
        if mics or loopbacks:
            return mics, loopbacks
    return _list_sounddevice_devices()


def find_device_by_index(
    device_index: int,
    is_loopback: bool = False,
) -> Optional[AudioDevice]:
    """Look up an AudioDevice descriptor by index across enumerated devices."""
    mics, lbs = list_audio_devices()
    pool = lbs if is_loopback else mics
    for dev in pool:
        if dev.index == device_index:
            return dev
    # Fallback search across both pools in case user selected a custom virtual device
    for dev in mics + lbs:
        if dev.index == device_index:
            return dev
    return None


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
