"""Unit tests for audio resampling, cross-platform devices, config, hardware, updater, and i18n."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import numpy as np

from localminutes.audio.capture import resample_float32_to_16k_mono, resample_to_16k_mono
from localminutes.audio.devices import (
    _list_sounddevice_devices,
    get_loopback_setup_hint,
    is_virtual_loopback_name,
)
from localminutes.config import get_config_path, load_settings, save_settings
from localminutes.hardware import (
    PROFILE_BALANCED,
    PROFILE_ECO,
    PROFILE_PERFORMANCE,
    HardwareProfile,
    classify_hardware_tier,
    compute_runtime_tuning,
    detect_hardware_profile,
    format_hardware_summary,
    get_writable_data_dir,
    normalize_arch,
    select_compute_type_candidates,
)
from localminutes.i18n import TRANSLATIONS, LanguageManager
from localminutes.models import AppSettings
from localminutes.updater import (
    check_for_updates,
    compute_file_sha256,
    is_newer_version,
    parse_semver,
    parse_sha256sums,
    select_platform_asset,
    verify_file_sha256,
)


def test_anti_aliased_polyphase_resampling_rejects_aliasing() -> None:
    """Polyphase FIR resampling should preserve 1 kHz tone while strongly rejecting 12 kHz alias."""
    sr = 48_000
    t = np.linspace(0.0, 1.0, sr, endpoint=False)
    in_band = 0.45 * np.sin(2.0 * np.pi * 1000.0 * t)
    out_of_band = 0.35 * np.sin(2.0 * np.pi * 12000.0 * t)
    sig = in_band + out_of_band
    mono_i16 = np.clip(sig * 32767.0, -32768, 32767).astype(np.int16)
    stereo_pcm = np.column_stack([mono_i16, mono_i16]).ravel().tobytes()

    out = resample_to_16k_mono(stereo_pcm, channels=2, sample_rate=sr)
    assert out.dtype == np.float32
    assert len(out) == 16_000
    assert float(np.max(np.abs(out))) <= 1.0

    t_16k = np.linspace(0.0, 1.0, len(out), endpoint=False)
    ideal = (0.45 * np.sin(2.0 * np.pi * 1000.0 * t_16k)).astype(np.float32)
    sl = slice(200, -200)
    snr_db = 10.0 * np.log10(
        (float(np.mean(ideal[sl] ** 2)) + 1e-12) / (float(np.mean((out[sl] - ideal[sl]) ** 2)) + 1e-12)
    )
    assert snr_db > 35.0

    # Edge cases: empty input and passthrough 16 kHz float32 stereo
    assert resample_to_16k_mono(b"", channels=2, sample_rate=48_000).size == 0
    stereo_2d = np.column_stack([np.full(160, 0.5, dtype=np.float32), np.full(160, -0.5, dtype=np.float32)])
    passthrough = resample_float32_to_16k_mono(stereo_2d, channels=2, sample_rate=16_000)
    assert len(passthrough) == 160
    assert np.allclose(passthrough, 0.0, atol=1e-5)


def test_cross_platform_device_classification_and_enumeration() -> None:
    assert is_virtual_loopback_name("BlackHole 2ch", platform_name="darwin") is True
    assert is_virtual_loopback_name("MacBook Pro Microphone", platform_name="darwin") is False
    assert is_virtual_loopback_name("Built-in Audio Analog Stereo.monitor", platform_name="linux") is True
    assert is_virtual_loopback_name("Monitor of HDMI Output", platform_name="linux") is True
    assert is_virtual_loopback_name("USB Condenser Mic", platform_name="linux") is False
    assert is_virtual_loopback_name("Stereo Mix (Realtek)", platform_name="win32") is True
    assert is_virtual_loopback_name("", platform_name="darwin") is False

    for plat in ("win32", "darwin", "linux"):
        for lang in ("en", "tr"):
            hint = get_loopback_setup_hint(lang=lang, platform_name=plat)
            assert isinstance(hint, str) and len(hint) > 15

    fake_devices = [
        {"name": "MacBook Pro Microphone", "max_input_channels": 1, "default_samplerate": 48000.0},
        {"name": "MacBook Pro Speakers", "max_input_channels": 0, "default_samplerate": 48000.0},
        {"name": "BlackHole 2ch", "max_input_channels": 2, "default_samplerate": 48000.0},
        {"name": "BlackHole 16ch", "max_input_channels": 16, "default_samplerate": 48000.0},
    ]

    class _FakeSD:
        class default:
            device = (0, 1)

        @staticmethod
        def query_devices():
            return fake_devices

    with patch("localminutes.audio.devices.sd", _FakeSD):
        mics, lbs = _list_sounddevice_devices(platform_name="darwin")
        assert len(mics) == 1
        assert mics[0].name == "MacBook Pro Microphone"
        assert mics[0].is_default is True
        assert len(lbs) == 2
        default_lb = next(d for d in lbs if d.is_default)
        assert default_lb.name == "BlackHole 2ch"
        assert "[Loopback]" in default_lb.display_name
        assert "[Mic]" in mics[0].display_name


def test_config_load_save_and_corrupt_recovery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALMINUTES_DATA_DIR", str(tmp_path))
    assert get_writable_data_dir() == tmp_path

    # Missing file returns defaults
    defaults = load_settings()
    assert defaults.whisper_model == "small"
    assert defaults.air_gapped_mode is False

    # Save & reload round-trip
    custom = AppSettings(
        ui_language="tr",
        air_gapped_mode=True,
        whisper_model="medium",
        custom_vocabulary="PostgreSQL, PyQt6, Andaç",
        llm_provider="local_extractive",
    )
    save_settings(custom)
    assert get_config_path().exists()
    reloaded = load_settings()
    assert reloaded.ui_language == "tr"
    assert reloaded.air_gapped_mode is True
    assert reloaded.whisper_model == "medium"
    assert reloaded.custom_vocabulary == "PostgreSQL, PyQt6, Andaç"

    # Partial JSON merges missing defaults safely
    get_config_path().write_text('{"ui_language": "tr", "unknown_future_key": 123}', encoding="utf-8")
    partial = load_settings()
    assert partial.ui_language == "tr"
    assert partial.whisper_model == "small"

    # Corrupt JSON falls back cleanly without crashing
    get_config_path().write_text("{corrupt json !!!", encoding="utf-8")
    recovered = load_settings()
    assert recovered == AppSettings()

    # Non-dict JSON falls back cleanly
    get_config_path().write_text("[1, 2, 3]", encoding="utf-8")
    assert load_settings() == AppSettings()


def test_hardware_detection_and_runtime_tuning() -> None:
    assert normalize_arch("AMD64") == "x86_64"
    assert normalize_arch("aarch64") == "arm64"
    assert normalize_arch("i686") == "x86"

    assert classify_hardware_tier(10, 10, ("neon", "dotprod"), "arm64") == PROFILE_PERFORMANCE
    assert classify_hardware_tier(2, 2, ("sse4_2",), "x86_64") == PROFILE_ECO
    assert classify_hardware_tier(4, 4, ("avx2",), "x86_64") == PROFILE_BALANCED

    cands = select_compute_type_candidates("int8", ("int8", "float32"))
    assert cands[0] == "int8"
    assert "float32" in cands

    fake_hw = HardwareProfile(
        os_name="Darwin",
        os_version="27.0.0",
        arch="arm64",
        cpu_name="Apple M1 Pro",
        logical_cores=10,
        physical_cores=10,
        is_apple_silicon=True,
        isa_features=("dotprod", "neon"),
        supported_ct2_types=("int8", "int8_float32", "float32"),
        recommended_tier=PROFILE_PERFORMANCE,
    )
    assert fake_hw.has_modern_simd is True
    tuning_auto = compute_runtime_tuning(fake_hw, requested_profile="auto")
    assert tuning_auto.effective_profile == PROFILE_PERFORMANCE
    assert 2 <= tuning_auto.whisper_threads <= 8

    tuning_eco = compute_runtime_tuning(fake_hw, requested_profile="eco")
    assert tuning_eco.effective_profile == PROFILE_ECO
    assert tuning_eco.whisper_threads <= 2

    summary_en = format_hardware_summary(fake_hw, tuning_auto, lang="en")
    summary_tr = format_hardware_summary(fake_hw, tuning_auto, lang="tr")
    assert "Apple M1 Pro" in summary_en and "0 MB VRAM" in summary_en
    assert "Yüksek Performans" in summary_tr

    live_hw = detect_hardware_profile(query_ct2=False)
    assert live_hw.logical_cores >= 1
    assert live_hw.physical_cores >= 1


def test_updater_semver_asset_selection_and_sha256(tmp_path: Path) -> None:
    assert parse_semver("v1.2.3") == (1, 2, 3, 1)
    assert parse_semver("1.2.3-rc.1") == (1, 2, 3, 0)
    assert is_newer_version("v1.0.1", "1.0.0") is True
    assert is_newer_version("1.0.0", "1.0.0-rc.1") is True
    assert is_newer_version("1.0.0", "1.0.0") is False
    assert is_newer_version("0.9.9", "1.0.0") is False

    assets = [
        {"name": "LocalMinutes-Setup-v1.1.0-Windows-x64.exe", "browser_download_url": "https://ex/win.exe", "size": 100},
        {"name": "LocalMinutes-Portable-v1.1.0-Windows-x64.zip", "browser_download_url": "https://ex/win.zip", "size": 90},
        {"name": "LocalMinutes-v1.1.0-macOS-arm64.dmg", "browser_download_url": "https://ex/mac.dmg", "size": 110},
        {"name": "LocalMinutes-v1.1.0-Linux-x86_64.tar.gz", "browser_download_url": "https://ex/lin.tar.gz", "size": 95},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://ex/SHA256SUMS.txt", "size": 5},
    ]

    win_name, win_url, _, win_sums = select_platform_asset(assets, platform_name="win32", machine="AMD64")
    assert win_name.endswith(".exe") and "Setup" in win_name and win_url == "https://ex/win.exe"
    assert win_sums == "https://ex/SHA256SUMS.txt"

    mac_name, _, _, _ = select_platform_asset(assets, platform_name="darwin", machine="arm64")
    assert mac_name.endswith("macOS-arm64.dmg")

    lin_name, _, _, _ = select_platform_asset(assets, platform_name="linux", machine="x86_64")
    assert lin_name.endswith(".tar.gz")

    sample = tmp_path / "payload.bin"
    sample.write_bytes(b"LocalMinutes-v1.0.0-verified-payload")
    digest = hashlib.sha256(sample.read_bytes()).hexdigest()
    assert compute_file_sha256(str(sample)) == digest
    assert verify_file_sha256(str(sample), digest) is True
    assert verify_file_sha256(str(sample), "0" * 64) is False

    sums_txt = f"{digest}  LocalMinutes-v1.0.0-macOS-arm64.dmg\n"
    assert parse_sha256sums(sums_txt, "LocalMinutes-v1.0.0-macOS-arm64.dmg") == digest
    assert parse_sha256sums(sums_txt, "other.dmg") is None

    # Network failure never raises
    with patch("localminutes.updater.urllib.request.urlopen", side_effect=OSError("offline")):
        info = check_for_updates(current_version="1.0.0")
        assert info.is_update_available is False
        assert info.error is not None


def test_i18n_bilingual_parity_and_formatting() -> None:
    en_keys = set(TRANSLATIONS["en"].keys())
    tr_keys = set(TRANSLATIONS["tr"].keys())
    assert en_keys == tr_keys, f"Mismatched i18n keys: {en_keys ^ tr_keys}"

    mgr = LanguageManager("en")
    assert mgr.t("archive_count", count=5) == "5 sessions"
    mgr.set_language("tr")
    assert mgr.lang == "tr"
    assert mgr.t("archive_count", count=5) == "5 oturum"
    assert mgr.t("nonexistent_key") == "nonexistent_key"

    fallback = LanguageManager("xx")
    assert fallback.lang == "en"
