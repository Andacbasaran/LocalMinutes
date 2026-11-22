# LocalMinutes

%100 offline, toplantıya bot sokmayan canlı toplantı ve ders deşifre + özet stüdyosu.

## Özellikler (v0.2.0)
- **Çift Kanallı Canlı Ses Yakalama:** Windows WASAPI loopback (`Karşı Taraf`) + mikrofon (`Sen`) ayrı kanallarda kayıt, gerçek zamanlı seviye ölçer ve opsiyonel ayrı WAV kaydı
- **Ses / Video Dosyası İçe Aktarma:** `.mp3`, `.wav`, `.m4a`, `.mp4`, `.mkv`, `.ogg`, `.flac`, `.webm` dosyalarını sürükle-bırak veya tek tıkla offline deşifre
- **Offline Deşifre (`faster-whisper`):** CTranslate2 INT8 CPU + Silero VAD, Ayarlar içinde Whisper model indirme ve önbellek yöneticisi
- **Etkileşimli Transkript Stüdyosu:** Satır içi metin/konuşmacı düzenleme, ⭐ önemli an işaretleme (`Ctrl+B`), konuşmacı ve işaretli an filtreleri, canlı kelime & konuşma payı istatistikleri
- **Şablonlu Akıllı Özetleme & Canlı Notlar:** `Genel Toplantı`, `Ders / Eğitim`, `Teknik / Sprint`, `Mülakat / Görüşme` şablonları; **Otomatik (Ollama → Yerleşik %100 Offline Motor)** veya opsiyonel OpenAI-uyumlu API desteği + canlı toplantı notları sekmesi
- **Tek Tıkla Dışa Aktarma:** Markdown (`.md`), Düz Metin (`.txt`), Altyazı (`.srt`) ve tam yedek JSON (`.json`)
- **Arşiv & Tam Metin Arama:** SQLite + FTS5 ile başlık, transkript, özet ve notlarda anında arama
- **Klavye Kısayolları & Sistem Tepsisi:** `Ctrl+R` (Başlat/Bitir), `Ctrl+P` (Duraklat), `Ctrl+B` (Anı İşaretle), `Ctrl+O` (Dosya İçe Aktar), `Ctrl+G` (Özetle), `Ctrl+F` (Ara), `Ctrl+N` (Yeni), `Ctrl+,` (Ayarlar)

## Teknoloji Yığını
- **Dil:** Python 3.10+
- **Arayüz:** PyQt6 Studio
- **Ses & AI:** `pyaudiowpatch` (WASAPI Loopback), `faster-whisper` (CTranslate2 INT8 + Silero VAD), `httpx` (Ollama / API) + yerleşik offline extractive özet motoru
- **Depolama:** SQLite + FTS5 tam metin arama

## Kurulum ve Çalıştırma
```powershell
uv venv .venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Testler
```powershell
.venv\Scripts\pytest.exe -v
```
