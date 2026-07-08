"""
Local file conversion helpers backed by FFmpeg.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from utils import find_ffmpeg, sanitize_filename

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[float, str], None]
ProcessCallback = Callable[[subprocess.Popen, Path], None]
CancelCallback = Callable[[], bool]


class ConversionCancelledError(RuntimeError):
    """Raised when an FFmpeg conversion is cancelled."""


@dataclass(frozen=True)
class ConversionPreset:
    key: str
    label: str
    description: str
    output_format: str
    ffmpeg_args: tuple[str, ...]
    requires_video: bool = False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "output_format": self.output_format,
            "requires_video": self.requires_video,
        }


class FileConverter:
    SUPPORTED_FORMATS = ("mp4", "mkv", "avi", "mov", "3gp", "mp3", "wav", "flac", "m4a")
    VIDEO_FORMATS = ("mp4", "mkv", "avi", "mov", "3gp")
    AUDIO_FORMATS = ("mp3", "wav", "flac", "m4a")

    _PRESETS: tuple[ConversionPreset, ...] = (
        ConversionPreset(
            key="constant_quality",
            label="Constant Quality",
            description="Balanced quality for everyday playback.",
            output_format="mp4",
            ffmpeg_args=(
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="small_size",
            label="Small Size",
            description="Smaller MP4 files for easier sharing and storage.",
            output_format="mp4",
            ffmpeg_args=(
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "30",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="feature_phone_240p",
            label="Feature Phone 240p",
            description="240p MP4 tuned for basic keypad and low-power devices.",
            output_format="mp4",
            ffmpeg_args=(
                "-vf",
                "scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2:black",
                "-r",
                "15",
                "-c:v",
                "libx264",
                "-profile:v",
                "baseline",
                "-level",
                "3.0",
                "-preset",
                "veryfast",
                "-b:v",
                "220k",
                "-maxrate",
                "240k",
                "-bufsize",
                "480k",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ac",
                "1",
                "-ar",
                "22050",
                "-b:a",
                "48k",
                "-movflags",
                "+faststart",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="feature_phone_144p",
            label="Feature Phone 144p",
            description="Smallest MP4 file for older keypad phones and tiny screens.",
            output_format="mp4",
            ffmpeg_args=(
                "-vf",
                "scale=176:144:force_original_aspect_ratio=decrease,pad=176:144:(ow-iw)/2:(oh-ih)/2:black",
                "-r",
                "12",
                "-c:v",
                "libx264",
                "-profile:v",
                "baseline",
                "-level",
                "1.3",
                "-preset",
                "veryfast",
                "-b:v",
                "120k",
                "-maxrate",
                "140k",
                "-bufsize",
                "280k",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "32k",
                "-movflags",
                "+faststart",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="constant_quality",
            label="Constant Quality",
            description="Reliable MKV output with strong video quality.",
            output_format="mkv",
            ffmpeg_args=(
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "22",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="small_size",
            label="Small Size",
            description="Compact MKV preset for lower storage use.",
            output_format="mkv",
            ffmpeg_args=(
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "29",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="lossless",
            label="Lossless",
            description="FFV1 video with FLAC audio for archival quality.",
            output_format="mkv",
            ffmpeg_args=(
                "-c:v",
                "ffv1",
                "-level",
                "3",
                "-coder",
                "1",
                "-context",
                "1",
                "-g",
                "1",
                "-c:a",
                "flac",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="constant_quality",
            label="Constant Quality",
            description="Classic AVI output for older players and editors.",
            output_format="avi",
            ffmpeg_args=(
                "-c:v",
                "mpeg4",
                "-qscale:v",
                "4",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="small_size",
            label="Small Size",
            description="Lower bitrate AVI for lightweight compatibility.",
            output_format="avi",
            ffmpeg_args=(
                "-c:v",
                "mpeg4",
                "-qscale:v",
                "7",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "128k",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="constant_quality",
            label="Constant Quality",
            description="MOV preset for editing and Apple-friendly workflows.",
            output_format="mov",
            ffmpeg_args=(
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="small_size",
            label="Small Size",
            description="Smaller MOV files when size matters more than fidelity.",
            output_format="mov",
            ffmpeg_args=(
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "29",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-movflags",
                "+faststart",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="feature_phone_240p",
            label="Feature Phone 240p",
            description="240p 3GP preset for legacy mobile playback.",
            output_format="3gp",
            ffmpeg_args=(
                "-vf",
                "scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2:black",
                "-r",
                "12",
                "-c:v",
                "h263",
                "-b:v",
                "180k",
                "-c:a",
                "aac",
                "-ac",
                "1",
                "-ar",
                "22050",
                "-b:a",
                "32k",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="feature_phone_144p",
            label="Feature Phone 144p",
            description="Very small 3GP files for the oldest keypad phones.",
            output_format="3gp",
            ffmpeg_args=(
                "-vf",
                "scale=176:144:force_original_aspect_ratio=decrease,pad=176:144:(ow-iw)/2:(oh-ih)/2:black",
                "-r",
                "10",
                "-c:v",
                "h263",
                "-b:v",
                "96k",
                "-c:a",
                "aac",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "24k",
            ),
            requires_video=True,
        ),
        ConversionPreset(
            key="mp3_320",
            label="MP3 320kbps",
            description="Best for music lovers who want top MP3 quality.",
            output_format="mp3",
            ffmpeg_args=("-vn", "-c:a", "libmp3lame", "-b:a", "320k"),
        ),
        ConversionPreset(
            key="mp3_192",
            label="MP3 192kbps",
            description="Balanced MP3 quality for everyday listening.",
            output_format="mp3",
            ffmpeg_args=("-vn", "-c:a", "libmp3lame", "-b:a", "192k"),
        ),
        ConversionPreset(
            key="mp3_128",
            label="MP3 128kbps",
            description="Small MP3 files that save storage space.",
            output_format="mp3",
            ffmpeg_args=("-vn", "-c:a", "libmp3lame", "-b:a", "128k"),
        ),
        ConversionPreset(
            key="m4a_256",
            label="M4A 256kbps",
            description="AAC quality tuned for modern phones and players.",
            output_format="m4a",
            ffmpeg_args=("-vn", "-c:a", "aac", "-b:a", "256k"),
        ),
        ConversionPreset(
            key="m4a_192",
            label="M4A 192kbps",
            description="Balanced AAC preset for portable listening.",
            output_format="m4a",
            ffmpeg_args=("-vn", "-c:a", "aac", "-b:a", "192k"),
        ),
        ConversionPreset(
            key="m4a_128",
            label="M4A 128kbps",
            description="Smaller AAC files for casual listening.",
            output_format="m4a",
            ffmpeg_args=("-vn", "-c:a", "aac", "-b:a", "128k"),
        ),
        ConversionPreset(
            key="lossless",
            label="Lossless",
            description="Uncompressed WAV audio with no quality loss.",
            output_format="wav",
            ffmpeg_args=("-vn", "-c:a", "pcm_s16le"),
        ),
        ConversionPreset(
            key="lossless",
            label="Lossless",
            description="FLAC audio for lossless compression and archiving.",
            output_format="flac",
            ffmpeg_args=("-vn", "-c:a", "flac"),
        ),
    )

    def __init__(self) -> None:
        self.ffmpeg_path, ffmpeg_message = find_ffmpeg()
        self.ffprobe_path = self._find_ffprobe(self.ffmpeg_path)
        logger.info(ffmpeg_message)
        if self.ffprobe_path:
            logger.info("ffprobe found: %s", self.ffprobe_path)
        else:
            logger.info("ffprobe not found, duration probing will use fallbacks")

    def list_formats(self) -> list[str]:
        return list(self.SUPPORTED_FORMATS)

    def list_presets(self, output_format: str) -> list[dict]:
        output_format = output_format.lower()
        return [preset.to_dict() for preset in self._PRESETS if preset.output_format == output_format]

    def get_preset(self, output_format: str, preset_key: str) -> ConversionPreset:
        output_format = output_format.lower()
        for preset in self._PRESETS:
            if preset.output_format == output_format and preset.key == preset_key:
                return preset
        raise ValueError(f"Unsupported preset '{preset_key}' for format '{output_format}'.")

    def is_audio_format(self, output_format: str) -> bool:
        return output_format.lower() in self.AUDIO_FORMATS

    def is_video_format(self, output_format: str) -> bool:
        return output_format.lower() in self.VIDEO_FORMATS

    def probe_source(self, source_path: str | Path) -> dict:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        info = {
            "path": str(source),
            "name": source.name,
            "size": source.stat().st_size,
            "duration": None,
            "has_video": None,
            "has_audio": None,
        }

        if self.ffprobe_path:
            cmd = [
                self.ffprobe_path,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-print_format",
                "json",
                str(source),
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    payload = json.loads(result.stdout)
                    streams = payload.get("streams", [])
                    info["has_video"] = any(stream.get("codec_type") == "video" for stream in streams)
                    info["has_audio"] = any(stream.get("codec_type") == "audio" for stream in streams)
                    duration = payload.get("format", {}).get("duration")
                    if duration not in (None, "", "N/A"):
                        info["duration"] = float(duration)
            except Exception as exc:
                logger.debug("ffprobe probe failed for %s: %s", source, exc)

        suffix = source.suffix.lower().lstrip(".")
        if info["has_video"] is None:
            if suffix in self.AUDIO_FORMATS:
                info["has_video"] = False
            elif suffix in self.VIDEO_FORMATS:
                info["has_video"] = True
            else:
                info["has_video"] = True
        if info["has_audio"] is None:
            info["has_audio"] = True

        return info

    def prepare_output_path(
        self,
        source_path: str | Path,
        output_format: str,
        preset_key: str,
        output_dir: str | Path,
    ) -> Path:
        source = Path(source_path).expanduser()
        output_dir_path = Path(output_dir).expanduser()
        output_dir_path.mkdir(parents=True, exist_ok=True)

        safe_stem = sanitize_filename(source.stem) or "converted_file"
        safe_slug = sanitize_filename(preset_key.replace("_", "-")) or "preset"
        base_name = f"{safe_stem}_{safe_slug}"
        candidate = output_dir_path / f"{base_name}.{output_format}"
        index = 1
        while candidate.exists():
            candidate = output_dir_path / f"{base_name} ({index}).{output_format}"
            index += 1
        return candidate

    def convert(
        self,
        source_path: str | Path,
        output_format: str,
        preset_key: str,
        output_dir: str | Path,
        progress_callback: Optional[ProgressCallback] = None,
        process_callback: Optional[ProcessCallback] = None,
        cancel_check: Optional[CancelCallback] = None,
    ) -> Path:
        self._ensure_ffmpeg()

        source = Path(source_path).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source}")

        output_format = output_format.lower()
        preset = self.get_preset(output_format, preset_key)
        media_info = self.probe_source(source)

        if self.is_video_format(output_format) and not media_info.get("has_video"):
            raise ValueError("Audio-only files can only be converted to audio formats.")
        if self.is_audio_format(output_format) and not media_info.get("has_audio"):
            raise ValueError("The selected file does not contain an audio stream.")
        if preset.requires_video and not media_info.get("has_video"):
            raise ValueError("The selected preset requires a video source file.")

        output_path = self.prepare_output_path(source, output_format, preset_key, output_dir)
        duration = media_info.get("duration")

        cmd = [
            self.ffmpeg_path,
            "-nostdin",
            "-i",
            str(source),
            *preset.ffmpeg_args,
            "-progress",
            "pipe:2",
            "-nostats",
            "-n",
            str(output_path),
        ]

        # Add thread limiting for CPU throttling
        cmd = self._add_thread_limiting(cmd)

        logger.info("Starting conversion: %s -> %s (%s)", source, output_path, preset.key)

        # Create process with CPU priority throttling
        process = self._create_throttled_process(cmd)

        if process_callback:
            process_callback(process, output_path)
        if progress_callback:
            progress_callback(0.0, "--")

        last_lines: list[str] = []
        elapsed_seconds = 0.0
        speed = "--"

        try:
            assert process.stderr is not None
            while True:
                if cancel_check and cancel_check() and process.poll() is None:
                    process.terminate()

                line = process.stderr.readline()
                if not line and process.poll() is not None:
                    break
                if not line:
                    continue

                text = line.strip()
                if not text:
                    continue
                last_lines.append(text)
                last_lines = last_lines[-20:]

                parsed_duration = self._parse_duration_seconds(text)
                if parsed_duration and not duration:
                    duration = parsed_duration

                if text.startswith("out_time="):
                    elapsed_seconds = self._parse_clock_seconds(text.split("=", 1)[1])
                elif text.startswith("speed="):
                    speed = text.split("=", 1)[1].strip() or speed
                elif "time=" in text:
                    maybe_time = self._extract_field_value(text, "time")
                    if maybe_time:
                        elapsed_seconds = self._parse_clock_seconds(maybe_time)
                    maybe_speed = self._extract_field_value(text, "speed")
                    if maybe_speed:
                        speed = maybe_speed

                if progress_callback and duration:
                    percent = max(0.0, min((elapsed_seconds / duration) * 100, 99.9))
                    progress_callback(percent, speed)

            return_code = process.wait()
        finally:
            if process.stderr:
                process.stderr.close()

        if cancel_check and cancel_check():
            raise ConversionCancelledError("Conversion cancelled.")

        if return_code != 0:
            tail = "\n".join(last_lines[-8:]).strip()
            raise RuntimeError(tail or "FFmpeg conversion failed.")

        if progress_callback:
            progress_callback(100.0, speed)

        logger.info("Conversion complete: %s", output_path)
        return output_path

    def _ensure_ffmpeg(self) -> None:
        if not self.ffmpeg_path:
            raise RuntimeError("FFmpeg is not available. Install FFmpeg or add it to PATH.")

    @staticmethod
    def _find_ffprobe(ffmpeg_path: Optional[str]) -> Optional[str]:
        if ffmpeg_path:
            ffmpeg_file = Path(ffmpeg_path)
            probe_name = "ffprobe.exe" if ffmpeg_file.suffix.lower() == ".exe" else "ffprobe"
            probe_candidate = ffmpeg_file.with_name(probe_name)
            if probe_candidate.exists():
                return str(probe_candidate)
        return shutil.which("ffprobe")

    @staticmethod
    def _parse_duration_seconds(text: str) -> Optional[float]:
        marker = "Duration:"
        if marker not in text:
            return None
        duration_text = text.split(marker, 1)[1].split(",", 1)[0].strip()
        return FileConverter._parse_clock_seconds(duration_text)

    @staticmethod
    def _parse_clock_seconds(value: str) -> float:
        parts = value.strip().split(":")
        if len(parts) != 3:
            return 0.0
        hours, minutes, seconds = parts
        try:
            return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)
        except ValueError:
            return 0.0

    @staticmethod
    def _extract_field_value(text: str, field_name: str) -> Optional[str]:
        token = f"{field_name}="
        if token not in text:
            return None
        remainder = text.split(token, 1)[1].strip()
        if " " in remainder:
            remainder = remainder.split(" ", 1)[0]
        return remainder.strip()

    def _add_thread_limiting(self, cmd: list[str]) -> list[str]:
        """Add thread limiting arguments to FFmpeg command for CPU throttling."""
        cmd = cmd.copy()
        # Insert -threads 2 after the input file (after -i and the input path)
        for i, arg in enumerate(cmd):
            if arg == "-i":
                # Insert after the input file path (i+2 is after the input file)
                cmd.insert(i + 2, "-threads")
                cmd.insert(i + 3, "2")
                break
        return cmd

    def _create_throttled_process(self, cmd: list[str]) -> subprocess.Popen:
        """Create a subprocess with CPU priority throttling."""
        import platform
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        
        # Apply CPU priority throttling based on platform
        try:
            if platform.system() == "Windows":
                import psutil
                p = psutil.Process(process.pid)
                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:
                # On Linux/macOS, use os.nice
                import os
                os.nice(10)
        except Exception as exc:
            logger.debug("Could not set process priority: %s", exc)
        
        return process
