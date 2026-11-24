# Security & Privacy Policy

## Supported Versions

| Version | Supported |
| :--- | :---: |
| `1.0.x` (Latest) | ✅ |
| `< 1.0.0` | ❌ |

## Privacy & Zero-Bot Offline Architecture

LocalMinutes is engineered from the ground up for confidential meetings, enterprise security reviews, medical/legal notes, and private study sessions:

- **Zero Meeting Bots:** LocalMinutes never joins your Zoom, Teams, Google Meet, or Discord call as a participant. Audio is captured strictly from your local OS audio subsystem.
- **100% On-Device Transcription & Search:** Speech recognition (`faster-whisper` CTranslate2 INT8), voice activity detection, SQLite WAL + FTS5 storage, offline extractive summarization, and BM25 Q&A execute entirely on your CPU with **0 MB VRAM** and **0 bytes uploaded**.
- **Strict Air-Gapped Privacy Mode:** Enabling **Strict Air-Gapped Privacy Mode** in *Settings & Telemetry* enforces **0 outbound HTTP requests** — disabling GitHub update checks, Ollama network probes, and external API providers while keeping offline summarization and BM25 Q&A fully functional.
- **Optional Local LLM / API Backends:**
  - **Local Ollama (`http://localhost:11434`):** Keeps summarization and Q&A 100% on your local machine.
  - **Optional OpenAI-Compatible API:** Used **only** if explicitly selected by the user; API keys are stored strictly in your local OS-native settings file (`settings.json`) and never transmitted elsewhere.
- **Local Data Storage Paths:**
  - **Windows:** `%APPDATA%\LocalMinutes\`
  - **macOS:** `~/Library/Application Support/LocalMinutes/`
  - **Linux:** `$XDG_DATA_HOME/localminutes/` (defaults to `~/.local/share/localminutes/`)

## Binary Integrity & Code Signing

Every official GitHub Release publishes a unified `SHA256SUMS.txt` manifest so you can verify download integrity before launching:

```powershell
# Windows (PowerShell)
Get-FileHash .\LocalMinutes-Setup-v1.0.0-Windows-x64.exe -Algorithm SHA256
```

```bash
# macOS
shasum -a 256 LocalMinutes-v1.0.0-macOS-arm64.dmg

# Linux
sha256sum -c --ignore-missing SHA256SUMS.txt
```

- **SignPath.io Open-Source Signing Roadmap:** See [`packaging/signpath/README.md`](packaging/signpath/README.md) for our SignPath Foundation setup to sign Windows releases automatically via GitHub Actions.

## Reporting a Vulnerability

If you discover a security or privacy vulnerability, **please do not open a public issue**. Instead:

1. Use **GitHub Private Vulnerability Reporting** (*Security → Advisories → Report a vulnerability*) on this repository, or
2. Contact the maintainer via the profile email listed at [github.com/Andacbasaran](https://github.com/Andacbasaran).

We aim to acknowledge all security reports within **48 hours** and release a fix as rapidly as possible.
