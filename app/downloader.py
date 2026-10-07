from __future__ import annotations

import copy
import re
import shutil
import threading
import time
import traceback
from collections import OrderedDict
from pathlib import Path
from typing import Any

import imageio_ffmpeg
import yt_dlp
from yt_dlp.utils import DownloadError

from .jobs import jobs
from .security import UnsafeURLError, validate_public_http_url
from .settings import DOWNLOAD_DIR, settings


class UserFacingDownloadError(RuntimeError):
    pass


# Large fields yt-dlp never needs to download the media; dropping them keeps cached info small.
_UNUSED_INFO_KEYS = ("automatic_captions", "subtitles", "heatmap", "comments")

# Prefer H.264 video and AAC audio so "best" and merged downloads produce MP4 files that play everywhere.
_COMPATIBLE_SORT = ["vcodec:h264", "res", "acodec:aac"]
_MERGE_CONTAINERS = "mp4/webm/mkv"

_CODEC_NAMES = (
    ("avc", "H.264"), ("h264", "H.264"), ("hev", "H.265"), ("hvc", "H.265"), ("h265", "H.265"),
    ("av01", "AV1"), ("vp09", "VP9"), ("vp9", "VP9"), ("vp8", "VP8"),
    ("mp4a", "AAC"), ("aac", "AAC"), ("opus", "Opus"), ("vorbis", "Vorbis"), ("mp3", "MP3"),
    ("flac", "FLAC"), ("ac-3", "AC-3"), ("ec-3", "E-AC-3"),
)
_AUDIO_EXTS = {"mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac", "weba"}
# Lower is preferred when two formats share a resolution and container.
_VIDEO_CODEC_RANK = {"H.264": 0, "H.265": 1, "AV1": 2, "VP9": 3}


class _InfoCache:
    """Short-lived cache of analyzed media so starting a download skips a second extraction."""

    def __init__(self, ttl_seconds: int, max_entries: int = 64) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._items: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, url: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(url)
            if not item:
                return None
            stored_at, info = item
            if time.monotonic() - stored_at > self._ttl:
                del self._items[url]
                return None
            self._items.move_to_end(url)
        # Callers mutate the info while downloading, so never hand out the cached object.
        return copy.deepcopy(info)

    def put(self, url: str, info: dict[str, Any]) -> None:
        with self._lock:
            self._items[url] = (time.monotonic(), info)
            self._items.move_to_end(url)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def discard(self, url: str) -> None:
        with self._lock:
            self._items.pop(url, None)


_info_cache = _InfoCache(settings.info_cache_minutes * 60)


def _js_runtimes() -> dict[str, dict[str, str]]:
    runtimes: dict[str, dict[str, str]] = {}
    if settings.enable_deno_runtime:
        deno = shutil.which("deno")
        if deno:
            runtimes["deno"] = {"executable": deno}
    if settings.enable_node_runtime:
        node = shutil.which("node") or shutil.which("nodejs")
        if node:
            runtimes["node"] = {"executable": node}
    return runtimes


def _base_ydl_opts() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": False,
        "noplaylist": not settings.allow_playlists,
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 6,
        "restrictfilenames": True,
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
        "max_filesize": settings.max_file_mb * 1024 * 1024,
        "ignoreerrors": False,
        "skip_unavailable_fragments": True,
        "windowsfilenames": True,
    }
    runtimes = _js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    return opts


def _duration_guard(info: dict[str, Any]) -> None:
    duration = info.get("duration")
    if duration and duration > settings.max_duration_seconds:
        raise UserFacingDownloadError(
            f"This media is longer than the configured limit of {settings.max_duration_seconds // 60} minutes."
        )


def _size_guard(info: dict[str, Any]) -> None:
    limit = settings.max_file_mb * 1024 * 1024
    for key in ("filesize", "filesize_approx"):
        size = info.get(key)
        if size and size > limit:
            raise UserFacingDownloadError(
                f"This media exceeds the configured size limit of {settings.max_file_mb} MB."
            )


def _flatten_single(info: dict[str, Any]) -> dict[str, Any]:
    if info.get("_type") in {"playlist", "multi_video"}:
        entries = [entry for entry in (info.get("entries") or []) if entry]
        if not settings.allow_playlists:
            if len(entries) == 1:
                return entries[0]
            raise UserFacingDownloadError("Playlists and multi-video pages are not supported in this deployment.")
    return info


def _extract(url: str) -> dict[str, Any]:
    """Extract media info once and cache it in the same form yt-dlp's --load-info-json accepts."""
    opts = _base_ydl_opts()
    opts["skip_download"] = True
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise UserFacingDownloadError(_clean_ydl_error(str(exc))) from exc
    except Exception as exc:
        raise UserFacingDownloadError("The media source could not be analyzed.") from exc

    if not info:
        raise UserFacingDownloadError("No downloadable media was found at that URL.")
    info = _flatten_single(info)
    for key in _UNUSED_INFO_KEYS:
        info.pop(key, None)
    # Drops the previous format selection and private keys; per-format cookies and headers are kept,
    # so a fresh YoutubeDL can download from this info without contacting the extractor again.
    info = yt_dlp.YoutubeDL.sanitize_info(info, remove_private_keys=True)
    _info_cache.put(url, info)
    return info


def _codec_name(codec: str | None) -> str | None:
    if not codec or codec == "none":
        return None
    lowered = codec.lower()
    for prefix, name in _CODEC_NAMES:
        if lowered.startswith(prefix):
            return name
    return codec.split(".")[0].upper()


def _format_size(f: dict[str, Any]) -> int | None:
    value = f.get("filesize") or f.get("filesize_approx")
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _bitrate(f: dict[str, Any], key: str) -> int | None:
    value = f.get(key)
    try:
        return round(float(value)) if value else None
    except (TypeError, ValueError):
        return None


def _is_drc(f: dict[str, Any]) -> bool:
    return str(f.get("format_id") or "").endswith("-drc") or "DRC" in str(f.get("format_note") or "")


def _safe_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    video: list[dict[str, Any]] = []
    audio: list[dict[str, Any]] = []
    for f in info.get("formats") or []:
        if f.get("has_drm"):
            continue
        fmt_id = str(f.get("format_id") or "")
        if not fmt_id:
            continue
        ext = (f.get("ext") or "").lower()
        # yt-dlp uses None for "unknown" and "none" for "absent". Direct file links usually report
        # no codecs at all, so treat them as a complete file unless the extension says audio.
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        if vcodec is None and acodec is None and ext in _AUDIO_EXTS:
            vcodec = "none"
        if vcodec == "none" and acodec == "none":
            continue
        height = f.get("height") or 0
        fps = round(f.get("fps") or 0)
        audio_only = vcodec == "none"
        if audio_only and _is_drc(f):
            continue
        item = {
            "id": fmt_id,
            "label": "",
            "ext": ext or "unknown",
            "height": height or None,
            "width": f.get("width"),
            "fps": fps or None,
            "filesize": _format_size(f),
            "combined": not audio_only and acodec != "none",
            "video_only": not audio_only and acodec == "none",
            "audio_only": audio_only,
            "vcodec": _codec_name(vcodec),
            "acodec": _codec_name(acodec),
            "abr": _bitrate(f, "abr"),
            "tbr": _bitrate(f, "tbr"),
            # Segmented (HLS/DASH) streams are slower to fetch than a single HTTPS file.
            "_streamed": "m3u8" in str(f.get("protocol")) or "dash" in str(f.get("protocol")),
        }
        if audio_only:
            item["label"] = f"{item['abr']} kbps" if item["abr"] else "Audio"
            audio.append(item)
        else:
            if height:
                item["label"] = f"{height}p{fps if fps > 30 else ''}"
            else:
                item["label"] = str(f.get("format_note") or "Original")
            video.append(item)

    # One row per resolution / frame-rate class / container. Prefer files that already contain audio
    # (no merge step), then the most compatible codec, then the higher bitrate.
    video.sort(key=lambda f: (
        -(f["height"] or 0),
        -(f["fps"] or 0),
        f["ext"] != "mp4",
        not f["combined"],
        f["_streamed"],
        _VIDEO_CODEC_RANK.get(f["vcodec"], 9),
        -(f["tbr"] or 0),
    ))
    selected: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for item in video:
        marker = (item["height"], (item["fps"] or 0) > 30, item["ext"])
        if marker in seen:
            continue
        seen.add(marker)
        selected.append(item)
        if len(selected) >= 16:
            break

    audio.sort(key=lambda f: (f["abr"] or f["tbr"] or 0, f["filesize"] or 0), reverse=True)
    selected.extend(audio[:4])
    for item in selected:
        item.pop("_streamed", None)
    return selected


def analyze_url(raw_url: str) -> dict[str, Any]:
    url = validate_public_http_url(raw_url)
    info = _extract(url)
    _duration_guard(info)
    _size_guard(info)
    formats = _safe_formats(info)
    if not formats:
        raise UserFacingDownloadError("No non-DRM downloadable formats were found.")
    return {
        "title": info.get("title") or "Untitled media",
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "extractor": info.get("extractor_key") or info.get("extractor"),
        "formats": formats,
        "best": {"id": "best", "label": "Best quality MP4", "ext": "mp4"},
        "audio": {"id": "audio", "label": "Audio (MP3)", "ext": "mp3"},
    }


def _clean_ydl_error(message: str) -> str:
    message = re.sub(r"^ERROR:\s*", "", message.strip())
    message = re.sub(r"\s+", " ", message)
    lowered = message.lower()
    if "drm" in lowered:
        return "This source appears to use DRM or protected playback and is not supported."
    if "not a bot" in lowered:
        return "The source is temporarily blocking requests from this server. Please try again later."
    if re.search(r"sign in|log(?:ged)?[ -]?in|cookies|credentials|private video|members[ -]only", lowered):
        return "This source requires authentication or account access, which this service does not accept."
    if "unsupported url" in lowered:
        return "This website or link is not supported. Try the URL of the page that plays the video."
    if "http error 404" in lowered:
        return "The media could not be found at that URL (404)."
    # Drop the "[extractor] id:" prefix and yt-dlp command-line advice meant for terminal users.
    message = re.sub(r"^\[[^\]]+\]\s*(?:[^\s:]+:\s*)?", "", message)
    message = re.split(r"\s(?:Use --|See https://github\.com/yt-dlp|Confirm you are on the latest version)", message)[0]
    return message[:300].strip() or "The source could not be processed."


def _allowed_format_ids(info: dict[str, Any]) -> set[str]:
    return {str(f.get("format_id")) for f in info.get("formats") or [] if f.get("format_id") and not f.get("has_drm")}


class _Progress:
    """Turns yt-dlp's per-file progress into one steadily rising percentage for the whole job.

    A merged download fetches video and audio one after the other; weighting each part by its
    expected size keeps the bar from jumping back to 0% when the second part starts.
    """

    _PP_MESSAGES = {
        "Merger": "Merging video and audio…",
        "ExtractAudio": "Converting to MP3…",
    }

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.weights: dict[str, float] = {}
        self.total_bytes: int | None = None
        self.done: set[str] = set()
        self.percent = 2
        self.last_push = 0.0

    def plan(self, parts: list[dict[str, Any]]) -> None:
        sizes = [_format_size(part) for part in parts]
        ids = [str(part.get("format_id")) for part in parts]
        if sizes and all(sizes):
            total = sum(sizes)
            self.total_bytes = total
            self.weights = {fid: size / total for fid, size in zip(ids, sizes)}
        else:
            self.weights = {fid: 1 / len(ids) for fid in ids} if ids else {}

    def hook(self, data: dict[str, Any]) -> None:
        status = data.get("status")
        fid = str((data.get("info_dict") or {}).get("format_id"))
        weight = self.weights.get(fid, 1.0)
        finished = sum(self.weights.get(done, 0) for done in self.done)

        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            part_total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            part_fraction = min(downloaded / part_total, 1) if part_total else 0
            fraction = min(finished + weight * part_fraction, 1)
            now = time.monotonic()
            percent = max(self.percent, 2 + int(fraction * 95))
            if percent == self.percent and now - self.last_push < 0.5:
                return
            self.percent, self.last_push = percent, now
            speed = data.get("speed")
            eta = data.get("eta")
            downloaded_total = None
            if self.total_bytes:
                downloaded_total = int(self.total_bytes * fraction)
                if speed:
                    eta = int((self.total_bytes - downloaded_total) / speed)
            jobs.update(
                self.job_id,
                status="downloading",
                progress=percent,
                message="Downloading media…",
                speed=speed,
                eta=eta,
                downloaded_bytes=downloaded_total,
                total_bytes=self.total_bytes,
            )
        elif status == "finished":
            self.done.add(fid)
            done_fraction = min(sum(self.weights.get(d, 0) for d in self.done), 1)
            self.percent = max(self.percent, 2 + int(done_fraction * 95))
            all_done = done_fraction >= 0.999 or not self.weights
            jobs.update(
                self.job_id,
                status="processing" if all_done else "downloading",
                progress=self.percent,
                message="Finalizing media…" if all_done else "Downloading media…",
                speed=None,
                eta=None,
            )

    def postprocessor_hook(self, data: dict[str, Any]) -> None:
        if data.get("status") != "started":
            return
        message = self._PP_MESSAGES.get(data.get("postprocessor") or "")
        if message:
            self.percent = max(self.percent, 98)
            jobs.update(self.job_id, status="processing", progress=self.percent, message=message, speed=None, eta=None)


def _match_filter(info: dict[str, Any], *, incomplete: bool = False) -> str | None:
    if incomplete:
        return None
    try:
        _duration_guard(info)
        _size_guard(info)
    except UserFacingDownloadError as exc:
        return str(exc)
    if info.get("has_drm"):
        return "DRM-protected media is not supported."
    return None


def _check_downloadable(info: dict[str, Any], requested_format: str) -> None:
    _duration_guard(info)
    _size_guard(info)
    if info.get("has_drm"):
        raise UserFacingDownloadError("DRM-protected media is not supported.")
    if requested_format not in {"best", "audio"} and requested_format not in _allowed_format_ids(info):
        raise UserFacingDownloadError("The requested format is no longer available. Analyze the URL again.")


def _format_options(info: dict[str, Any], requested_format: str) -> dict[str, Any]:
    if requested_format == "audio":
        return {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    opts: dict[str, Any] = {"format_sort": _COMPATIBLE_SORT, "merge_output_format": _MERGE_CONTAINERS}
    if requested_format == "best":
        opts["format"] = "bestvideo*+bestaudio/best"
        return opts

    selected = next((f for f in info.get("formats") or [] if str(f.get("format_id")) == requested_format), None)
    if not selected or selected.get("has_drm"):
        raise UserFacingDownloadError("That format is not available.")
    has_video = selected.get("vcodec") != "none"
    has_audio = selected.get("acodec") != "none"
    if has_video and not has_audio:
        # Pair video-only streams with audio in the same container so the merge stays a fast stream copy.
        ext = (selected.get("ext") or "").lower()
        audio_ext = {"mp4": "m4a", "m4v": "m4a", "mov": "m4a", "webm": "webm"}.get(ext)
        choices = [f"{requested_format}+bestaudio[ext={audio_ext}]"] if audio_ext else []
        choices += [f"{requested_format}+bestaudio", requested_format]
        opts["format"] = "/".join(choices)
    else:
        opts["format"] = requested_format
    return opts


def _clear_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def _run_download(job_id: str, job_dir: Path, info: dict[str, Any], requested_format: str) -> None:
    progress = _Progress(job_id)
    opts = _base_ydl_opts()
    opts.update({
        "paths": {"home": str(job_dir), "temp": str(job_dir / "tmp")},
        "outtmpl": {"default": "%(title).120s-%(id)s.%(ext)s"},
        "progress_hooks": [progress.hook],
        "postprocessor_hooks": [progress.postprocessor_hook],
        "match_filter": _match_filter,
        "nopart": False,
        "continuedl": True,
    })
    opts.update(_format_options(info, requested_format))
    with yt_dlp.YoutubeDL(opts) as ydl:
        # Resolve the format selection first (no network) so progress can be weighted per part.
        planned = ydl.process_ie_result(copy.deepcopy(info), download=False)
        progress.plan(planned.get("requested_formats") or [planned])
        ydl.process_ie_result(info, download=True)


def download_job(job_id: str, raw_url: str, requested_format: str) -> None:
    job_dir = DOWNLOAD_DIR / job_id
    jobs.update(job_id, status="analyzing", progress=1, message="Preparing download…")
    try:
        url = validate_public_http_url(raw_url)
        info = _info_cache.get(url)
        from_cache = info is not None
        if info is None:
            jobs.update(job_id, message="Checking available media…")
            info = copy.deepcopy(_extract(url))
        _check_downloadable(info, requested_format)
        title = info.get("title") or "media"

        try:
            _run_download(job_id, job_dir, info, requested_format)
        except DownloadError:
            if not from_cache:
                raise
            # Media URLs from the analysis step can expire; refresh them once before giving up.
            _info_cache.discard(url)
            _clear_dir(job_dir)
            jobs.update(job_id, status="analyzing", progress=1, message="Refreshing media links…")
            info = copy.deepcopy(_extract(url))
            _check_downloadable(info, requested_format)
            _run_download(job_id, job_dir, info, requested_format)

        candidates = [p for p in job_dir.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
        if not candidates:
            raise UserFacingDownloadError(
                f"No file was produced. The media may exceed the {settings.max_file_mb} MB size limit."
            )
        output = max(candidates, key=lambda p: p.stat().st_mtime)
        jobs.update(
            job_id,
            status="ready",
            progress=100,
            message="Ready to download",
            title=title,
            filename=output.name,
            file_path=str(output),
            speed=None,
            eta=None,
            total_bytes=output.stat().st_size,
        )
    except (UserFacingDownloadError, UnsafeURLError) as exc:
        jobs.update(job_id, status="error", progress=0, message="Download failed", error=str(exc))
    except DownloadError as exc:
        jobs.update(job_id, status="error", progress=0, message="Download failed", error=_clean_ydl_error(str(exc)))
    except Exception:
        traceback.print_exc()
        jobs.update(job_id, status="error", progress=0, message="Download failed", error="An unexpected server error occurred while processing this media.")
