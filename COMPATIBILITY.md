# Compatibility Matrix & Platform Setup Guide

**LocalMinutes** runs natively on **Windows x64**, **macOS (Apple Silicon & Intel)**, and **Linux (PipeWire & PulseAudio)** without joining any meeting bot.

---

## 1. Operating System & Audio Loopback Matrix

| Platform | Mic Channel (`You`) | System Audio Loopback (`Remote`) | Setup Requirement |
| :--- | :--- | :--- | :--- |
| **Windows 10 / 11 (x64)** | Native WASAPI (`pyaudiowpatch`) | Native WASAPI Loopback (`pyaudiowpatch`) | **Zero setup** — works out-of-the-box for any speaker/headset output |
| **macOS 12+ (Apple Silicon M1–M4 / Intel)** | Native CoreAudio (`sounddevice`) | Virtual Loopback (`BlackHole 2ch`, `Loopback Audio`, `VB-Cable`) | Mic works immediately; for system audio run `brew install blackhole-2ch` + create a Multi-Output Device in *Audio MIDI Setup* |
| **Linux (Ubuntu / Fedora / Arch — PipeWire)** | Native PortAudio (`sounddevice`) | Auto-detected `.monitor` / `Monitor of ...` sinks | Install `libportaudio2`; PipeWire monitor sinks appear automatically (use `pavucontrol` or `qpwgraph` if needed) |
| **Linux (PulseAudio)** | Native PortAudio (`sounddevice`) | Auto-detected `.monitor` sinks | Install `libportaudio2`; select `Monitor of <Output>` in Settings |

> **Single-Channel Fallback:** Even if no loopback device is configured (for example, on a fresh macOS install before adding BlackHole 2ch), LocalMinutes automatically records your microphone cleanly instead of blocking startup.

---

## 2. Verified Meeting, Lecture & Media Applications

Because LocalMinutes captures audio locally from the OS audio mixer, **zero bots join your calls** and any audio-producing application works automatically:

| Application / Source | Windows (WASAPI) | macOS (CoreAudio + BlackHole) | Linux (PipeWire) | Notes |
| :--- | :---: | :---: | :---: | :--- |
| **Zoom Workplace** | ✅ Verified | ✅ Verified | ✅ Verified | Zero participant bot; supports dual `You` / `Remote` separation |
| **Microsoft Teams** | ✅ Verified | ✅ Verified | ✅ Verified | Works with both Desktop & Web Teams |
| **Google Meet (Chrome / Arc / Edge / Firefox)** | ✅ Verified | ✅ Verified | ✅ Verified | Captures browser tab output cleanly |
| **Discord / Slack Huddles** | ✅ Verified | ✅ Verified | ✅ Verified | Ideal for engineering standups & huddles |
| **Cisco Webex / Jitsi / BigBlueButton** | ✅ Verified | ✅ Verified | ✅ Verified | Works seamlessly for university & enterprise calls |
| **YouTube / Udemy / Coursera / Local Videos** | ✅ Verified | ✅ Verified | ✅ Verified | Capture live OR drag-and-drop `MP4/MKV/MP3/WAV/M4A/WEBM` directly |

---

## 3. Whisper CPU Models Guide (0 MB VRAM)

LocalMinutes uses `faster-whisper` (CTranslate2 `INT8` with automatic fallback to `INT8_FLOAT32` / `FLOAT32`) strictly on CPU:

| Model | Download Size | RAM Footprint | Recommended Hardware | Accuracy (EN / TR) |
| :--- | :---: | :---: | :--- | :--- |
| **`tiny`** | ~75 MB | ~250 MB | Low-power laptops / 2-core CPUs | Fast draft notes |
| **`base`** | ~145 MB | ~350 MB | Ultrabooks / 4-core CPUs | Good for clear English |
| **`small`** *(Default)* | ~485 MB | ~800 MB | Modern 4–10 core CPUs (M1–M4 / Ryzen / Core i5+) | **Best balance for EN & TR** |
| **`medium`** | ~1.5 GB | ~2.1 GB | 8+ core CPUs (M1 Pro / Ryzen 7 / Core i7+) | High accuracy & heavy accents |
| **`large-v3-turbo`** | ~1.6 GB | ~2.3 GB | Fast Apple Silicon / high-core desktop CPUs | Near-studio accuracy across 99 languages |

> **Tip for Technical Jargon & EN/TR Code-Switching:** Add project names, acronyms, and speaker names into **Settings → Custom Vocabulary (`initial_prompt`)** (e.g., `Kubernetes, PyQt6, PostgreSQL, CTranslate2, Andaç, OKR`) to dramatically boost Whisper recognition accuracy.

---

## 4. Summarization & Local Q&A Backends

| Backend | Internet Required | Setup | Best For |
| :--- | :---: | :--- | :--- |
| **Built-in Offline Engine (Extractive + BM25)** | **No (0 HTTP)** | Zero setup (bundled) | Air-gapped laptops, instant `12.9 ms` summaries & `9.09 ms` Q&A citations |
| **Local Ollama (`qwen2.5:7b`, `llama3.1:8b`, `gemma3:4b`)** | **No (Localhost)** | Install [Ollama](https://ollama.com) + `ollama pull qwen2.5:7b` | Rich abstractive summaries, Granola-style note enhancement & deep Q&A |
| **OpenAI-Compatible API (LM Studio / vLLM / OpenAI)** | Optional | Base URL + optional API Key in Settings | Custom self-hosted inference servers or cloud fallback |

---

## 5. Help Expand This Matrix

Tested LocalMinutes on another Linux distro, audio interface, or Ollama model? Open an [Audio / App Compatibility Report](https://github.com/Andacbasaran/LocalMinutes/issues/new?template=compatibility_report.yml) or submit a PR!
