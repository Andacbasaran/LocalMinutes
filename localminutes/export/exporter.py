"""One-click exporters for Markdown (.md), Plain Text (.txt), and SubRip (.srt)."""

from __future__ import annotations

from pathlib import Path

from localminutes.models import Meeting


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_srt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm for SubRip (.srt)."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_markdown(meeting: Meeting) -> str:
    """Render a full meeting (summary + transcript) as structured Markdown."""
    lines: list[str] = [
        f"# {meeting.title}",
        "",
        f"- **Tarih:** {meeting.created_at}",
        f"- **Süre:** {format_timestamp(meeting.duration_sec)}",
        f"- **Dil:** {meeting.language}",
        "",
    ]

    if meeting.summary:
        s = meeting.summary
        lines.append("## Özet")
        lines.append("")
        if s.overview:
            lines.append(s.overview.strip())
            lines.append("")
        if s.key_points:
            lines.append("### Öne Çıkan Noktalar")
            for item in s.key_points:
                lines.append(f"- {item}")
            lines.append("")
        if s.decisions:
            lines.append("### Alınan Kararlar")
            for item in s.decisions:
                lines.append(f"- {item}")
            lines.append("")
        if s.action_items:
            lines.append("### Yapılacaklar (Action Items)")
            for item in s.action_items:
                lines.append(f"- [ ] {item}")
            lines.append("")

    lines.append("## Transkript")
    lines.append("")
    if not meeting.segments:
        lines.append("_Henüz transkript kaydı bulunmuyor._")
    else:
        for seg in meeting.segments:
            ts = format_timestamp(seg.start_sec)
            lines.append(f"**[{ts}] {seg.speaker}:** {seg.text.strip()}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_txt(meeting: Meeting) -> str:
    """Render a meeting as clean plain text."""
    lines: list[str] = [
        meeting.title,
        "=" * len(meeting.title),
        f"Tarih: {meeting.created_at} | Süre: {format_timestamp(meeting.duration_sec)}",
        "",
    ]

    if meeting.summary:
        s = meeting.summary
        lines.append("ÖZET")
        lines.append("-" * 40)
        if s.overview:
            lines.append(s.overview.strip())
            lines.append("")
        if s.key_points:
            lines.append("Öne Çıkan Noktalar:")
            for item in s.key_points:
                lines.append(f"  * {item}")
            lines.append("")
        if s.decisions:
            lines.append("Alınan Kararlar:")
            for item in s.decisions:
                lines.append(f"  * {item}")
            lines.append("")
        if s.action_items:
            lines.append("Yapılacaklar:")
            for item in s.action_items:
                lines.append(f"  [ ] {item}")
            lines.append("")

    lines.append("TRANSKRİPT")
    lines.append("-" * 40)
    for seg in meeting.segments:
        ts = format_timestamp(seg.start_sec)
        lines.append(f"[{ts}] {seg.speaker}: {seg.text.strip()}")

    return "\n".join(lines).rstrip() + "\n"


def format_srt(meeting: Meeting) -> str:
    """Render transcript segments as SubRip (.srt) subtitles."""
    blocks: list[str] = []
    for idx, seg in enumerate(meeting.segments, start=1):
        start = _format_srt_time(seg.start_sec)
        end_sec = seg.end_sec if seg.end_sec > seg.start_sec else seg.start_sec + 2.0
        end = _format_srt_time(end_sec)
        blocks.append(f"{idx}\n{start} --> {end}\n{seg.speaker}: {seg.text.strip()}\n")
    return "\n".join(blocks)


def export_meeting(meeting: Meeting, output_path: Path | str, fmt: str) -> Path:
    """Write a meeting to disk in 'md', 'txt', or 'srt' format."""
    path = Path(output_path)
    fmt_clean = fmt.lower().lstrip(".")
    if fmt_clean in ("md", "markdown"):
        content = format_markdown(meeting)
    elif fmt_clean == "txt":
        content = format_txt(meeting)
    elif fmt_clean == "srt":
        content = format_srt(meeting)
    else:
        raise ValueError(f"Desteklenmeyen dışa aktarma formatı: {fmt}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
