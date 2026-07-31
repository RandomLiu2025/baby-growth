import json
import logging
import math
import os
import shutil
import struct
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import filetype

from .config import settings


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic"}
VIDEO_EXT = {".mp4", ".webm", ".ogg", ".ogv", ".mov", ".m4v", ".mkv"}
CHUNK_BYTES = 5 * 1024 * 1024
MAX_CHUNK_BYTES = 10 * 1024 * 1024
_MANIFEST_LOCK = threading.Lock()
_UPLOAD_LOCKS = tuple(threading.RLock() for _ in range(64))
_UPLOAD_SLOTS = threading.BoundedSemaphore(max(1, settings.MAX_CONCURRENT_UPLOADS))
_MEDIA_SLOTS = threading.BoundedSemaphore(max(1, settings.MAX_CONCURRENT_MEDIA_JOBS))
logger = logging.getLogger(__name__)


class UploadValidationError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def upload_lock(upload_id: str):
    try:
        bucket = int(upload_id[:8], 16) % len(_UPLOAD_LOCKS)
    except (TypeError, ValueError):
        bucket = 0
    with _UPLOAD_LOCKS[bucket]:
        yield


@contextmanager
def upload_slot():
    if not _UPLOAD_SLOTS.acquire(blocking=False):
        raise UploadValidationError("上传任务较多，请稍后重试", 429)
    try:
        yield
    finally:
        _UPLOAD_SLOTS.release()


@contextmanager
def media_job_slot():
    acquired = _MEDIA_SLOTS.acquire(timeout=max(1, settings.MEDIA_PROCESS_TIMEOUT_SECONDS))
    if not acquired:
        raise UploadValidationError("媒体处理任务繁忙，请稍后重试", 429)
    try:
        yield
    finally:
        _MEDIA_SLOTS.release()


def classify_upload(filename: str | None, content_type: str | None):
    ext = os.path.splitext(filename or "")[1].lower()
    reported = (content_type or "").lower()
    if ext in IMAGE_EXT:
        if reported and not reported.startswith("image/"):
            return None, ext, 0
        return "image", ext, settings.MAX_IMAGE_MB
    if ext in VIDEO_EXT:
        if reported and not (reported.startswith("video/") or reported == "application/octet-stream"):
            return None, ext, 0
        return "video", ext, settings.MAX_VIDEO_MB
    return None, ext, 0


def validate_file_content(path: str, expected_kind: str) -> None:
    detected = filetype.guess(path)
    if not detected or not detected.mime.startswith(f"{expected_kind}/"):
        raise UploadValidationError("文件内容与扩展名或 MIME 类型不一致")


def ensure_storage_capacity(upload_dir: str, required_bytes: int) -> None:
    os.makedirs(upload_dir, exist_ok=True)
    reserve = max(0, settings.MIN_UPLOAD_FREE_MB) * 1024 * 1024
    free = shutil.disk_usage(upload_dir).free
    if free - max(0, int(required_bytes)) < reserve:
        raise UploadValidationError(
            f"存储空间不足，上传后需至少保留 {settings.MIN_UPLOAD_FREE_MB}MB 可用空间",
            507,
        )


def _jpeg_dimensions(path: str) -> tuple[int, int] | None:
    frame_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    try:
        with open(path, "rb") as handle:
            if handle.read(2) != b"\xff\xd8":
                return None
            while True:
                byte = handle.read(1)
                while byte and byte != b"\xff":
                    byte = handle.read(1)
                if not byte:
                    return None
                marker = handle.read(1)
                while marker == b"\xff":
                    marker = handle.read(1)
                if not marker or marker in {b"\xd9", b"\xda"}:
                    return None
                if marker[0] in range(0xD0, 0xD8) or marker == b"\x01":
                    continue
                raw_length = handle.read(2)
                if len(raw_length) != 2:
                    return None
                length = struct.unpack(">H", raw_length)[0]
                if length < 2:
                    return None
                if marker[0] in frame_markers:
                    frame = handle.read(5)
                    if len(frame) != 5:
                        return None
                    return struct.unpack(">HH", frame[1:5])[::-1]
                handle.seek(length - 2, os.SEEK_CUR)
    except OSError:
        return None


def _webp_dimensions(header: bytes) -> tuple[int, int] | None:
    if len(header) < 30 or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
        return None
    kind = header[12:16]
    if kind == b"VP8X" and len(header) >= 30:
        width = int.from_bytes(header[24:27], "little") + 1
        height = int.from_bytes(header[27:30], "little") + 1
        return width, height
    if kind == b"VP8 " and len(header) >= 30 and header[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(header[26:28], "little") & 0x3FFF
        height = int.from_bytes(header[28:30], "little") & 0x3FFF
        return width, height
    if kind == b"VP8L" and len(header) >= 25 and header[20] == 0x2F:
        bits = int.from_bytes(header[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def _image_dimensions(path: str) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as handle:
            header = handle.read(64)
    except OSError:
        return None
    if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24 and header[12:16] == b"IHDR":
        return struct.unpack(">II", header[16:24])
    if header[:6] in {b"GIF87a", b"GIF89a"} and len(header) >= 10:
        return struct.unpack("<HH", header[6:10])
    if header.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(path)
    return _webp_dimensions(header)


def _ffprobe(path: str) -> dict | None:
    executable = shutil.which("ffprobe")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [
                executable,
                "-v", "error",
                "-show_entries", "stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate:format=duration,format_name",
                "-of", "json",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=max(1, settings.MEDIA_PROBE_TIMEOUT_SECONDS),
            check=True,
        )
        return json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
        raise UploadValidationError("媒体文件无法解析或编码不受支持") from exc


def _frame_rate(value) -> float:
    if not value or value in {"0/0", "N/A"}:
        return 0
    try:
        numerator, denominator = str(value).split("/", 1)
        return float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0


def validate_media_constraints(path: str, kind: str) -> None:
    if kind == "image":
        dimensions = _image_dimensions(path)
        if dimensions:
            width, height = dimensions
            if width < 1 or height < 1:
                raise UploadValidationError("图片尺寸无效")
            if settings.MAX_IMAGE_PIXELS > 0 and width * height > settings.MAX_IMAGE_PIXELS:
                raise UploadValidationError(
                    f"图片像素过大，最多允许 {settings.MAX_IMAGE_PIXELS} 像素",
                    413,
                )
            return

    probe = _ffprobe(path)
    if not probe:
        return
    video_stream = next(
        (stream for stream in probe.get("streams") or [] if stream.get("codec_type") == "video"),
        None,
    )
    if not video_stream:
        raise UploadValidationError("媒体文件不包含可用的视频或图片画面")
    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    if kind == "image":
        if settings.MAX_IMAGE_PIXELS > 0 and width * height > settings.MAX_IMAGE_PIXELS:
            raise UploadValidationError(
                f"图片像素过大，最多允许 {settings.MAX_IMAGE_PIXELS} 像素",
                413,
            )
        return
    if width < 1 or height < 1:
        raise UploadValidationError("视频分辨率无效")
    if settings.MAX_VIDEO_PIXELS > 0 and width * height > settings.MAX_VIDEO_PIXELS:
        raise UploadValidationError("视频分辨率过高", 413)
    duration_value = (probe.get("format") or {}).get("duration")
    try:
        duration = float(duration_value or 0)
    except (TypeError, ValueError):
        duration = 0
    if settings.MAX_VIDEO_DURATION_SECONDS > 0 and duration > settings.MAX_VIDEO_DURATION_SECONDS:
        raise UploadValidationError(
            f"视频时长超过 {settings.MAX_VIDEO_DURATION_SECONDS} 秒上限",
            413,
        )
    fps = _frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
    if settings.MAX_VIDEO_FPS > 0 and fps > settings.MAX_VIDEO_FPS + 0.01:
        raise UploadValidationError(f"视频帧率超过 {settings.MAX_VIDEO_FPS:g} FPS 上限", 413)


def video_processing_plan(path: str) -> dict:
    probe = _ffprobe(path)
    if not probe:
        return {
            "action": "keep",
            "videoCodec": "",
            "audioCodecs": [],
            "warning": "ffprobe 不可用，未检查浏览器兼容性",
        }
    streams = probe.get("streams") or []
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video_stream:
        raise UploadValidationError("视频文件不包含可用画面")
    video_codec = str(video_stream.get("codec_name") or "").lower()
    audio_codecs = {
        str(stream.get("codec_name") or "").lower()
        for stream in streams
        if stream.get("codec_type") == "audio"
    }
    audio_codecs.discard("")
    suffix = Path(path).suffix.lower()
    mp4_audio = {"aac", "mp3"}
    webm_audio = {"opus", "vorbis"}
    if suffix in {".mp4", ".m4v"} and video_codec == "h264" and audio_codecs <= mp4_audio:
        action = "keep"
    elif suffix == ".webm" and video_codec in {"vp8", "vp9", "av1"} and audio_codecs <= webm_audio:
        action = "keep"
    elif video_codec == "h264" and audio_codecs <= mp4_audio:
        action = "remux"
    else:
        action = "transcode"
    return {
        "action": action,
        "videoCodec": video_codec,
        "audioCodecs": sorted(audio_codecs),
        "warning": "",
    }


def _video_command(executable: str, source: str, destination: str, action: str) -> list[str]:
    command = [
        executable,
        "-y",
        "-i", source,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-sn",
        "-dn",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
    ]
    if action == "remux":
        command.extend(["-c", "copy"])
    else:
        command.extend([
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-threads", "2",
            "-c:a", "aac",
            "-b:a", "128k",
        ])
    command.extend(["-movflags", "+faststart", destination])
    return command


def _run_video_command(command: list[str]) -> None:
    try:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=max(1, settings.MEDIA_PROCESS_TIMEOUT_SECONDS),
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise UploadValidationError("视频兼容处理超时") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UploadValidationError("视频兼容处理失败") from exc


def normalize_video_for_browser(path: str) -> tuple[str, str, str]:
    plan = video_processing_plan(path)
    action = plan["action"]
    if action == "keep":
        sanitize_media_metadata(path, "video")
        validate_file_content(path, "video")
        return path, action, plan.get("warning") or ""
    executable = shutil.which("ffmpeg")
    if not executable:
        return path, "keep", "ffmpeg 不可用，视频可能无法在部分浏览器播放"
    source = Path(path)
    output_path = source.with_name(f"{source.stem}_normalized.mp4")
    temp_path = source.with_name(f"{source.stem}_normalized.uploading.mp4")
    ensure_storage_capacity(str(source.parent), source.stat().st_size)
    selected_action = action
    try:
        try:
            _run_video_command(_video_command(executable, str(source), str(temp_path), selected_action))
        except UploadValidationError:
            if selected_action != "remux":
                raise
            try:
                temp_path.unlink()
            except OSError:
                pass
            selected_action = "transcode"
            _run_video_command(_video_command(executable, str(source), str(temp_path), selected_action))
        if not temp_path.is_file() or temp_path.stat().st_size < 1:
            raise UploadValidationError("视频兼容处理未生成有效文件")
        if temp_path.stat().st_size > settings.MAX_VIDEO_MB * 1024 * 1024:
            raise UploadValidationError(f"兼容处理后的视频超过 {settings.MAX_VIDEO_MB}MB 上限", 413)
        validate_file_content(str(temp_path), "video")
        validate_media_constraints(str(temp_path), "video")
        os.replace(temp_path, output_path)
        return str(output_path), selected_action, ""
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def _strip_jpeg_metadata(data: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        return data
    output = bytearray(data[:2])
    position = 2
    removable = {0xE1, 0xED, 0xFE}
    while position < len(data):
        marker_start = position
        if data[position] != 0xFF:
            raise UploadValidationError("JPEG 元数据结构损坏")
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            raise UploadValidationError("JPEG 元数据结构损坏")
        marker = data[position]
        position += 1
        if marker in {0xD9, 0xDA}:
            output.extend(data[marker_start:])
            return bytes(output)
        if marker in range(0xD0, 0xD8) or marker == 0x01:
            output.extend(data[marker_start:position])
            continue
        if position + 2 > len(data):
            raise UploadValidationError("JPEG 元数据结构损坏")
        length = int.from_bytes(data[position:position + 2], "big")
        segment_end = position + length
        if length < 2 or segment_end > len(data):
            raise UploadValidationError("JPEG 元数据结构损坏")
        if marker not in removable:
            output.extend(data[marker_start:segment_end])
        position = segment_end
    raise UploadValidationError("JPEG 文件缺少图像数据")


def _strip_png_metadata(data: bytes) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        return data
    output = bytearray(signature)
    position = len(signature)
    removable = {b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"}
    found_end = False
    while position + 12 <= len(data):
        length = int.from_bytes(data[position:position + 4], "big")
        chunk_end = position + 12 + length
        if chunk_end > len(data):
            raise UploadValidationError("PNG 元数据结构损坏")
        chunk_type = data[position + 4:position + 8]
        if chunk_type not in removable:
            output.extend(data[position:chunk_end])
        position = chunk_end
        if chunk_type == b"IEND":
            found_end = True
            break
    if not found_end or position != len(data):
        raise UploadValidationError("PNG 元数据结构损坏")
    return bytes(output)


def _strip_webp_metadata(data: bytes) -> bytes:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return data
    chunks = bytearray()
    position = 12
    while position + 8 <= len(data):
        chunk_type = data[position:position + 4]
        length = int.from_bytes(data[position + 4:position + 8], "little")
        padded = length + (length % 2)
        chunk_end = position + 8 + padded
        if chunk_end > len(data):
            raise UploadValidationError("WebP 元数据结构损坏")
        if chunk_type not in {b"EXIF", b"XMP "}:
            payload = bytearray(data[position + 8:position + 8 + length])
            if chunk_type == b"VP8X" and payload:
                payload[0] &= ~0x0C
            chunks.extend(chunk_type)
            chunks.extend(len(payload).to_bytes(4, "little"))
            chunks.extend(payload)
            if len(payload) % 2:
                chunks.append(0)
        position = chunk_end
    if position != len(data):
        raise UploadValidationError("WebP 元数据结构损坏")
    body = b"WEBP" + bytes(chunks)
    return b"RIFF" + len(body).to_bytes(4, "little") + body


def _write_replacement(path: str, content: bytes) -> None:
    temp_path = f"{path}.metadata.tmp"
    try:
        with open(temp_path, "wb") as handle:
            handle.write(content)
        os.replace(temp_path, path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def _strip_video_metadata(path: str) -> None:
    executable = shutil.which("ffmpeg")
    if not executable:
        logger.warning("ffmpeg 不可用，视频容器元数据未清理：%s", os.path.basename(path))
        return
    detected = filetype.guess(path)
    extension = detected.extension if detected else "mp4"
    temp_path = f"{path}.metadata.{extension}"
    try:
        subprocess.run(
            [
                executable,
                "-y",
                "-i", path,
                "-map", "0",
                "-map_metadata", "-1",
                "-map_chapters", "-1",
                "-c", "copy",
                temp_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=max(1, settings.MEDIA_PROBE_TIMEOUT_SECONDS * 2),
            check=True,
        )
        if not os.path.isfile(temp_path) or os.path.getsize(temp_path) < 1:
            raise UploadValidationError("视频元数据清理失败")
        validate_file_content(temp_path, "video")
        os.replace(temp_path, path)
    except subprocess.TimeoutExpired as exc:
        raise UploadValidationError("视频元数据清理超时") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UploadValidationError("视频元数据清理失败") from exc
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


def sanitize_media_metadata(path: str, kind: str) -> None:
    if kind == "video":
        _strip_video_metadata(path)
        return
    with open(path, "rb") as handle:
        content = handle.read()
    if content.startswith(b"\xff\xd8"):
        sanitized = _strip_jpeg_metadata(content)
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        sanitized = _strip_png_metadata(content)
    elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        sanitized = _strip_webp_metadata(content)
    else:
        return
    if sanitized != content:
        _write_replacement(path, sanitized)


def convert_heic_to_jpeg(source_path: str, destination_path: str) -> None:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise UploadValidationError("当前服务未安装 ffmpeg，无法转换 HEIC 图片")
    validate_file_content(source_path, "image")
    validate_media_constraints(source_path, "image")
    try:
        subprocess.run(
            [
                executable,
                "-y",
                "-i", source_path,
                "-frames:v", "1",
                "-map_metadata", "-1",
                "-q:v", "2",
                destination_path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=max(1, settings.MEDIA_PROBE_TIMEOUT_SECONDS * 4),
            check=True,
        )
        if not os.path.isfile(destination_path) or os.path.getsize(destination_path) < 1:
            raise UploadValidationError("HEIC 图片转换失败")
        if os.path.getsize(destination_path) > settings.MAX_IMAGE_MB * 1024 * 1024:
            raise UploadValidationError(f"转换后的图片超过 {settings.MAX_IMAGE_MB}MB 上限", 413)
        validate_file_content(destination_path, "image")
        validate_media_constraints(destination_path, "image")
        sanitize_media_metadata(destination_path, "image")
    except subprocess.TimeoutExpired as exc:
        try:
            os.remove(destination_path)
        except OSError:
            pass
        raise UploadValidationError("HEIC 图片转换超时") from exc
    except (OSError, subprocess.CalledProcessError) as exc:
        try:
            os.remove(destination_path)
        except OSError:
            pass
        raise UploadValidationError("HEIC 图片转换失败") from exc
    except Exception:
        try:
            os.remove(destination_path)
        except OSError:
            pass
        raise


def chunks_dir(upload_dir: str) -> str:
    directory = os.path.join(upload_dir, ".chunks")
    os.makedirs(directory, exist_ok=True)
    return directory


def cleanup_stale_chunks(upload_dir: str) -> None:
    directory = chunks_dir(upload_dir)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.CHUNK_TTL_HOURS)
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            modified = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
            if modified < cutoff:
                os.remove(path)
        except OSError:
            continue


def cleanup_stale_temporary_files(upload_dir: str) -> None:
    root = Path(upload_dir)
    if not root.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.CHUNK_TTL_HOURS)
    for path in root.iterdir():
        if not path.is_file() or path.is_symlink() or not path.name.endswith((".uploading", ".tmp")):
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                path.unlink()
        except OSError:
            continue


def _manifest_path(directory: str, upload_id: str) -> str:
    return os.path.join(directory, f"{upload_id}.json")


def part_path(directory: str, upload_id: str, index: int) -> str:
    return os.path.join(directory, f"{upload_id}_{index:04d}")


def _read_manifest(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        raise UploadValidationError("分片上传状态损坏，请重新上传", 409)


def _write_manifest(path: str, manifest: dict) -> dict:
    manifest = {**manifest, "updatedAt": _now_iso()}
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False)
    os.replace(temp_path, path)
    return manifest


def bind_manifest(
    upload_dir: str,
    upload_id: str,
    user_id: int,
    filename: str,
    file_size: int,
    total: int,
) -> dict:
    kind, _, limit_mb = classify_upload(filename, None)
    if not kind:
        raise UploadValidationError(f"不支持的文件类型：{filename or '未命名'}")
    limit = limit_mb * 1024 * 1024
    if file_size < 1 or file_size > limit:
        raise UploadValidationError(f"文件大小无效或超过 {limit_mb}MB 上限", 413)
    expected_parts = max(1, math.ceil(file_size / CHUNK_BYTES))
    if total != expected_parts:
        raise UploadValidationError("分片总数与文件大小不匹配")

    directory = chunks_dir(upload_dir)
    path = _manifest_path(directory, upload_id)
    expected = {
        "uploadId": upload_id,
        "userId": user_id,
        "filename": filename,
        "fileSize": file_size,
        "total": total,
    }
    with upload_lock(upload_id), _MANIFEST_LOCK:
        current = _read_manifest(path)
        if current:
            if any(current.get(key) != value for key, value in expected.items()):
                raise UploadValidationError("uploadId 已绑定到另一上传任务", 409)
            return current

        ensure_storage_capacity(upload_dir, file_size)
        created_at = _now_iso()
        manifest = {**expected, "state": "uploading", "createdAt": created_at, "updatedAt": created_at}
        return _write_manifest(path, manifest)


def require_manifest(
    upload_dir: str,
    upload_id: str,
    user_id: int,
    filename: str,
    file_size: int,
    total: int,
) -> dict:
    directory = chunks_dir(upload_dir)
    manifest = _read_manifest(_manifest_path(directory, upload_id))
    if not manifest:
        raise UploadValidationError("上传任务不存在或已过期", 409)
    expected = {
        "uploadId": upload_id,
        "userId": user_id,
        "filename": filename,
        "fileSize": file_size,
        "total": total,
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise UploadValidationError("上传任务元数据不一致", 409)
    manifest.setdefault("state", "uploading")
    return manifest


def expected_part_size(file_size: int, index: int) -> int:
    return min(CHUNK_BYTES, max(0, file_size - index * CHUNK_BYTES))


def upload_status(
    upload_dir: str,
    upload_id: str,
    user_id: int,
    filename: str,
    file_size: int,
    total: int,
) -> dict:
    with upload_lock(upload_id):
        manifest = require_manifest(upload_dir, upload_id, user_id, filename, file_size, total)
        state = manifest.get("state") or "uploading"
        received = []
        if state != "completed":
            directory = chunks_dir(upload_dir)
            for index in range(total):
                path = part_path(directory, upload_id, index)
                try:
                    if os.path.isfile(path) and os.path.getsize(path) == expected_part_size(file_size, index):
                        received.append(index)
                except OSError:
                    continue
        return {
            "uploadId": upload_id,
            "state": state,
            "received": received,
            "total": total,
            "result": manifest.get("result") if state == "completed" else None,
        }


def publish_part(
    upload_dir: str,
    upload_id: str,
    user_id: int,
    filename: str,
    file_size: int,
    total: int,
    index: int,
    temp_path: str,
) -> dict:
    with upload_lock(upload_id):
        manifest = require_manifest(upload_dir, upload_id, user_id, filename, file_size, total)
        state = manifest.get("state") or "uploading"
        if state == "completed":
            try:
                os.remove(temp_path)
            except OSError:
                pass
            return manifest
        if state != "uploading":
            raise UploadValidationError("上传任务正在合并，请稍后查询结果", 409)
        destination = part_path(chunks_dir(upload_dir), upload_id, index)
        os.replace(temp_path, destination)
        path = _manifest_path(chunks_dir(upload_dir), upload_id)
        return _write_manifest(path, manifest)


def begin_completion(upload_dir: str, manifest: dict, target_name: str) -> dict:
    state = manifest.get("state") or "uploading"
    if state == "completed":
        return manifest
    selected = manifest.get("targetName") or target_name
    path = _manifest_path(chunks_dir(upload_dir), manifest["uploadId"])
    return _write_manifest(path, {**manifest, "state": "completing", "targetName": selected})


def reset_completion(upload_dir: str, manifest: dict) -> dict:
    path = _manifest_path(chunks_dir(upload_dir), manifest["uploadId"])
    values = {key: value for key, value in manifest.items() if key not in {"targetName", "result", "completedAt"}}
    return _write_manifest(path, {**values, "state": "uploading"})


def mark_completed(upload_dir: str, manifest: dict, result: dict) -> dict:
    path = _manifest_path(chunks_dir(upload_dir), manifest["uploadId"])
    return _write_manifest(
        path,
        {**manifest, "state": "completed", "completedAt": _now_iso(), "result": result},
    )


def cancel_upload(upload_dir: str, upload_id: str, user_id: int) -> bool:
    with upload_lock(upload_id):
        directory = chunks_dir(upload_dir)
        manifest = _read_manifest(_manifest_path(directory, upload_id))
        if not manifest:
            return False
        if manifest.get("userId") != user_id:
            raise UploadValidationError("上传任务不存在", 404)
        if (manifest.get("state") or "uploading") == "completed":
            raise UploadValidationError("已完成的上传不能取消", 409)
        for path in Path(directory).glob(f"{upload_id}*"):
            try:
                if path.is_file() and not path.is_symlink():
                    path.unlink()
            except OSError:
                continue
        return True


def remove_upload_parts(upload_dir: str, upload_id: str, total: int, keep_manifest: bool = False) -> None:
    directory = chunks_dir(upload_dir)
    paths = [] if keep_manifest else [_manifest_path(directory, upload_id)]
    paths.extend(part_path(directory, upload_id, index) for index in range(total))
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass
