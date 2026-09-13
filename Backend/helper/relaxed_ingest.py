"""Personal ingestion defaults; years are never fabricated."""
from __future__ import annotations

import re

from Backend.helper.metadata import extract_default_id, metadata
from Backend.helper.metadata.parse import parse_media_name

CHANNEL_AUDIO = {
    "my malay dubbed": "Malay Dubbed",
    "my ani dub": "Malay Dubbed",
    "my indonesia dubbed": "Indonesian Dubbed",
}
_DUB = re.compile(r"(?i)\b(?:malay|bahasa\s+melayu|indonesian|indonesia)\s+(?:dubbed|dub)\b")
_SUFFIX = re.compile(r"(?i)(\.(?:mkv|mp4|avi|mov|webm|m4v|zip)(?:\.\d{2,3})?)$")
_GENERIC = re.compile(r"(?i)^(?:(?:vid|video|movie|file|document|unknown)[\s_\-\d]*|unknown_file)$")


def clean_name(value: str) -> str:
    value = re.sub(r"https?://\S+|(?<!\w)@\w+", " ", value or "")
    value = _DUB.sub(" ", value)
    value = re.sub(r"(?i)\.(?:id|ms)(?=\.(?:mkv|mp4)$)", "", value)
    value = re.sub(r"(?im)^\s*(?:movie\s+name|title|filename)\s*:\s*", "", value)
    # Preserve Unicode letters and meaningful title punctuation.
    value = "".join(c if c.isalnum() or c in " ._-()[]'&:+!?/\n" else " " for c in value)
    return re.sub(r"\s+", " ", value).strip()


def channel_audio(message) -> str:
    origin = getattr(message, "forward_origin", None)
    for chat in (getattr(message, "forward_from_chat", None),
                 getattr(origin, "chat", None), getattr(message, "chat", None)):
        name = " ".join((getattr(chat, "title", "") or "").casefold().split())
        if name in CHANNEL_AUDIO:
            return CHANNEL_AUDIO[name]
    return ""


def message_candidates(message) -> list[str]:
    media = getattr(message, "video", None) or getattr(message, "document", None)
    caption = getattr(message, "caption", None) or ""
    filename = getattr(media, "file_name", None) or ""
    # A proper underlying filename can rescue an advertising-only caption.
    sources = [caption, filename]
    parsed_sources = [parse_media_name(clean_name(s)) for s in sources if s]
    explicit_quality = next((p["quality"] for p in parsed_sources if p.get("quality")), None)
    candidates = []
    for source in sources:
        name = clean_name(source)
        parsed = parse_media_name(name) if name else {}
        title = parsed.get("title") or ""
        if not title or _GENERIC.fullmatch(title.strip()):
            continue
        quality = parsed.get("quality") or explicit_quality or "1080p"
        if not parsed.get("quality"):
            suffix = _SUFFIX.search(name)
            pos = suffix.start() if suffix else len(name)
            name = name[:pos].rstrip() + " " + str(quality) + name[pos:]
        if name not in candidates:
            candidates.append(name)
    return candidates


def display_name(result: dict, candidate: str, audio: str) -> str:
    # Keep split grouping/combined labels exactly as indexed.
    if result.get("group_key") or result.get("season_number") == 0:
        suffix = _SUFFIX.search(candidate)
        pos = suffix.start() if suffix else len(candidate)
        return candidate[:pos].rstrip() + (" " + audio if audio else "") + candidate[pos:]
    parts = [result.get("title") or parse_media_name(candidate).get("title") or candidate]
    if result.get("media_type") == "tv":
        season, episode = result.get("season_number"), result.get("episode_number")
        if season is not None and episode is not None:
            parts.append(f"S{int(season):02d}E{int(episode):02d}")
    else:
        # Only use a year supplied by the resolver or the original text.
        year = result.get("year") or parse_media_name(candidate).get("year")
        if year:
            parts.append(str(year))
    parts.extend([str(result.get("quality") or "1080p"), audio])
    suffix = _SUFFIX.search(candidate)
    return " ".join(str(p) for p in parts if p) + (suffix.group() if suffix else ".mkv")


async def metadata_for_message(message, channel, msg_id, override_id=None, season_hint=None):
    caption = getattr(message, "caption", None) or ""
    media = getattr(message, "video", None) or getattr(message, "document", None)
    filename = getattr(media, "file_name", None) or ""
    selected_id = override_id or extract_default_id(caption) or extract_default_id(filename)
    audio = channel_audio(message)
    if not audio:
        match = _DUB.search(caption + " " + filename)
        audio = match.group() if match else ""
    candidates = message_candidates(message)
    if not candidates and selected_id:
        candidates = ["1080p"]  # ID identifies the movie even without a title.
    for candidate in candidates:
        result = await metadata(candidate, channel, msg_id,
                                override_id=selected_id, season_hint=season_hint)
        if result:
            return display_name(result, candidate, audio), result
    return caption or filename, None
