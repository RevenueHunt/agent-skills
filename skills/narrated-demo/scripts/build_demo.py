#!/usr/bin/env python3
"""Build a narrated screencast from a raw browser recording and narration plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PACING_GAPS = {"tight": 0.5, "normal": 0.9, "relaxed": 1.2}
TTS_CACHE_VERSION = 2


class CommandError(RuntimeError):
    pass


def run(command: list[str], *, label: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run quietly on success and retain actionable output on failure."""
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise CommandError(f"{label or command[0]} could not start: {error}") from error

    if result.returncode != 0:
        diagnostics = (result.stderr or result.stdout or "No subprocess diagnostics.").strip()
        if len(diagnostics) > 6_000:
            diagnostics = diagnostics[-6_000:]
        raise CommandError(
            f"{label or command[0]} failed ({result.returncode})\n"
            f"Command: {shlex.join(command)}\n{diagnostics}"
        )
    return result


def probe_duration(path: Path) -> float:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        label=f"probe duration for {path.name}",
    )
    return float(result.stdout.strip())


def probe_media(path: Path) -> dict[str, object]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-show_entries",
            "stream=index,codec_name,codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        label=f"probe media for {path.name}",
    )
    return json.loads(result.stdout)


def timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def subtitle_text(text: str) -> str:
    """Preserve authored linguistic breaks; never slice prose by word count."""
    lines = [" ".join(line.split()) for line in text.strip().splitlines()]
    if not 1 <= len(lines) <= 2 or not all(lines):
        raise ValueError("Each subtitle must have one or two non-empty lines; split it into natural cues.")
    if any(len(line) > 42 for line in lines):
        raise ValueError(
            "Subtitle lines must be at most 42 characters. Author a natural line break "
            "or split the sentence into separate cue segments; see references/subtitles.md."
        )
    return "\n".join(lines)


def build_subtitles(
    segments: list[dict[str, object]], starts: list[float], ends: list[float]
) -> str:
    cues: list[str] = []
    for index, (segment, start, end) in enumerate(zip(segments, starts, ends, strict=True), 1):
        text = subtitle_text(str(segment["text"]))
        duration = end - start
        if not 5 / 6 <= duration <= 7:
            raise ValueError(
                f"Subtitle {index} lasts {duration:.2f}s; expected 0.83–7s. "
                "Merge a short cue or split a long cue at a natural phrase boundary."
            )
        cps = len(" ".join(text.split())) / duration
        if cps > 20:
            raise ValueError(
                f"Subtitle {index} needs {cps:.1f} characters/second (maximum 20). "
                "Slow the narration or rewrite the spoken text and subtitle together."
            )
        cues.append(f"{index}\n{timestamp(start)} --> {timestamp(end)}\n{text}")
    return "\n\n".join(cues) + "\n"


def load_plan(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text())
    segments = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(segments, list) or not segments:
        raise ValueError("Narration plan must be a non-empty list or contain a non-empty 'segments' list")

    normalized: list[dict[str, object]] = []
    for index, segment in enumerate(segments, 1):
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise ValueError(f"Segment {index} must contain string field 'text'")
        text = segment["text"].strip()
        if not text:
            raise ValueError(f"Segment {index} has empty text")
        try:
            text = subtitle_text(text)
        except ValueError as error:
            raise ValueError(f"Segment {index}: {error}") from error
        anchor = segment.get("anchor")
        valid_anchor = (
            anchor is None
            or isinstance(anchor, str) and bool(anchor.strip())
            or isinstance(anchor, (int, float)) and not isinstance(anchor, bool) and anchor >= 0
        )
        if not valid_anchor:
            raise ValueError(f"Segment {index} anchor must be a non-negative number or marker name")
        normalized.append(
            {
                "text": text,
                "anchor": anchor.strip() if isinstance(anchor, str) else float(anchor) if anchor is not None else None,
            }
        )
    return normalized


def load_timeline(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    payload = json.loads(path.read_text())
    markers = payload.get("markers") if isinstance(payload, dict) and "markers" in payload else payload
    if not isinstance(markers, dict):
        raise ValueError("Timeline must be an object or contain a 'markers' object")

    normalized: dict[str, float] = {}
    for name, value in markers.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Timeline marker names must be non-empty strings")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Timeline marker {name!r} must be a non-negative number")
        normalized[name] = float(value)
    return normalized


def resolve_anchors(
    segments: list[dict[str, object]], timeline: dict[str, float], video_speed: float
) -> list[dict[str, object]]:
    resolved: list[dict[str, object]] = []
    for index, segment in enumerate(segments, 1):
        anchor = segment["anchor"]
        if isinstance(anchor, str):
            if anchor not in timeline:
                raise ValueError(f"Segment {index} references missing timeline marker {anchor!r}")
            resolved.append({**segment, "marker": anchor, "anchor": timeline[anchor] / video_speed})
        else:
            resolved.append(dict(segment))
    return resolved


def schedule(
    segments: list[dict[str, object]], durations: list[float], gap: float, initial: float
) -> tuple[list[float], list[float]]:
    starts: list[float] = []
    ends: list[float] = []
    cursor = initial
    for index, (segment, duration) in enumerate(zip(segments, durations, strict=True)):
        anchor = segment["anchor"]
        # A marker starts a visual phase. Unanchored cues continue the same speech.
        if index and anchor is not None:
            cursor += gap
        start = max(cursor, float(anchor)) if anchor is not None else cursor
        end = start + duration
        starts.append(start)
        ends.append(end)
        cursor = end
    return starts, ends


def choose_audio_speed(
    segments: list[dict[str, object]],
    durations: list[float],
    gap: float,
    initial: float,
    target: float,
    max_speed: float,
) -> float:
    natural_end = schedule(segments, durations, gap, initial)[1][-1]
    if natural_end <= target - 0.25:
        return 1.0

    fastest_end = schedule(
        segments, [duration / max_speed for duration in durations], gap, initial
    )[1][-1]
    if fastest_end > target - 0.25:
        raise ValueError(
            f"Narration ends at {natural_end:.2f}s and cannot fit a {target:.2f}s video "
            f"without exceeding the {max_speed:.2f}x narration-speed limit. "
            "Use --duration auto, increase --duration, or shorten the script."
        )

    low, high = 1.0, max_speed
    for _ in range(30):
        middle = (low + high) / 2
        end = schedule(segments, [duration / middle for duration in durations], gap, initial)[1][-1]
        if end <= target - 0.25:
            high = middle
        else:
            low = middle
    return high


def parse_requested_duration(value: str) -> float | None:
    if value == "auto":
        return None
    try:
        duration = float(value)
    except ValueError as error:
        raise ValueError("--duration must be 'auto' or a number greater than one") from error
    if duration <= 1:
        raise ValueError("--duration must be greater than one")
    return duration


def filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def tts_cache_path(cache_dir: Path, text: str) -> Path:
    digest = hashlib.sha256(
        json.dumps(
            {
                "version": TTS_CACHE_VERSION,
                "text": text,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf8")
    ).hexdigest()[:24]
    return cache_dir / f"{digest}.wav"


def audio_file_is_valid(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 128:
        return False
    try:
        return probe_duration(path) > 0.05
    except (CommandError, ValueError):
        return False


def prepare_raw_narration(
    segments: list[dict[str, object]], work: Path
) -> tuple[list[Path], list[float]]:
    from audio8_tts import synthesize_many

    cache_dir = work / "tts-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Visual line breaks must not cause the TTS model to synthesize separate utterances.
    texts = [" ".join(str(segment["text"]).split()) for segment in segments]
    paths = [tts_cache_path(cache_dir, text) for text in texts]
    missing = [
        (text, path)
        for text, path in zip(texts, paths, strict=True)
        if not audio_file_is_valid(path)
    ]
    reused = len(paths) - len(missing)
    print(f"Narration cache: {reused} reused, {len(missing)} to generate")
    if missing:
        synthesize_many(missing)
    durations = [probe_duration(path) for path in paths]
    return paths, durations


def prepare_audio(
    raw_audio: list[Path], work: Path, audio_speed: float
) -> tuple[list[Path], list[float]]:
    ready_dir = work / "ready-audio"
    ready_dir.mkdir(parents=True, exist_ok=True)
    audio: list[Path] = []
    durations: list[float] = []
    for index, path in enumerate(raw_audio, 1):
        converted = ready_dir / f"{path.stem}-{audio_speed:.8f}.wav"
        if not audio_file_is_valid(converted):
            command = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(path)]
            if audio_speed > 1.000001:
                command += ["-filter:a", f"atempo={audio_speed:.8f}"]
            command += ["-ar", "44100", "-ac", "2", str(converted)]
            run(command, label=f"prepare narration segment {index}")
        audio.append(converted)
        durations.append(probe_duration(converted))
    return audio, durations


def validate_media(path: Path, target_duration: float, *, require_subtitles: bool = False) -> dict[str, object]:
    probe = probe_media(path)
    streams = probe.get("streams")
    if not isinstance(streams, list):
        raise ValueError(f"{path.name} has no readable streams")
    codecs = {(stream.get("codec_type"), stream.get("codec_name")) for stream in streams if isinstance(stream, dict)}
    if ("video", "h264") not in codecs:
        raise ValueError(f"{path.name} does not contain H.264 video")
    if ("audio", "aac") not in codecs:
        raise ValueError(f"{path.name} does not contain AAC audio")
    if require_subtitles and ("subtitle", "subrip") not in codecs:
        raise ValueError(f"{path.name} does not contain a SubRip subtitle stream")
    actual_duration = float(probe.get("format", {}).get("duration", 0))
    if abs(actual_duration - target_duration) > 0.2:
        raise ValueError(
            f"{path.name} duration is {actual_duration:.3f}s; expected {target_duration:.3f}s ±0.2s"
        )
    return probe


def detect_volume(path: Path) -> tuple[float, float]:
    result = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        label=f"volume check for {path.name}",
    )
    mean_match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stderr)
    max_match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stderr)
    if not mean_match or not max_match:
        raise ValueError(f"Could not verify audio volume in {path.name}")
    mean_volume = float(mean_match.group(1))
    max_volume = float(max_match.group(1))
    if mean_volume < -80:
        raise ValueError(f"{path.name} appears silent: mean volume is {mean_volume:.1f} dB")
    return mean_volume, max_volume


def create_contact_sheet(qa_dir: Path, frame_count: int) -> Path:
    columns = 2 if frame_count <= 4 else 3
    rows = math.ceil(frame_count / columns)
    output = qa_dir / "contact-sheet.jpg"
    run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            "1",
            "-pattern_type",
            "glob",
            "-i",
            str(qa_dir / "frame-*.jpg"),
            "-vf",
            f"scale=480:-1,tile={columns}x{rows}:padding=8:margin=8:color=white",
            "-frames:v",
            "1",
            str(output),
        ],
        label="create QA contact sheet",
    )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True, help="Raw screen recording (any ffmpeg-readable format)")
    parser.add_argument("--plan", type=Path, required=True, help="JSON narration plan")
    parser.add_argument("--timeline", type=Path, help="JSON marker timeline emitted by the recorder")
    parser.add_argument("--output", type=Path, required=True, help="Final burned-subtitle MP4")
    parser.add_argument(
        "--duration",
        default="auto",
        help="Target seconds or 'auto' (default); auto pads the final frame instead of speeding speech",
    )
    parser.add_argument("--pacing", choices=PACING_GAPS, default="tight")
    parser.add_argument("--initial-silence", type=float, default=0.8)
    parser.add_argument("--max-narration-speed", type=float, default=1.15)
    parser.add_argument("--qa-offset", type=float, default=0.8)
    parser.add_argument("--also-mkv", action="store_true", help="Also create an MKV with soft subtitles")
    parser.add_argument("--work-dir", type=Path, help="Persistent directory for narration/build cache")
    args = parser.parse_args()

    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise ValueError(f"{executable} is required but was not found on PATH")
    if not args.raw.is_file():
        raise ValueError(f"Raw recording does not exist: {args.raw}")
    if args.initial_silence < 0 or args.qa_offset < 0:
        raise ValueError("--initial-silence and --qa-offset must be non-negative")
    if not 1 <= args.max_narration_speed <= 2:
        raise ValueError("--max-narration-speed must be between 1 and 2")

    requested_duration = parse_requested_duration(args.duration)
    segments = load_plan(args.plan)
    timeline = load_timeline(args.timeline)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.work_dir:
        work = args.work_dir
        work.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="narrated-demo-")
        work = Path(temporary.name)

    try:
        raw_duration = probe_duration(args.raw)
        raw_audio, raw_durations = prepare_raw_narration(segments, work)
        gap = PACING_GAPS[args.pacing]

        if requested_duration is None:
            resolved_segments = resolve_anchors(segments, timeline, 1.0)
            natural_ends = schedule(
                resolved_segments, raw_durations, gap, args.initial_silence
            )[1]
            target_duration = math.ceil(max(raw_duration, natural_ends[-1] + 0.5) * 10) / 10
            video_speed = 1.0
            audio_speed = 1.0
        else:
            target_duration = requested_duration
            video_speed = raw_duration / target_duration if raw_duration > target_duration else 1.0
            resolved_segments = resolve_anchors(segments, timeline, video_speed)
            audio_speed = choose_audio_speed(
                resolved_segments,
                raw_durations,
                gap,
                args.initial_silence,
                target_duration,
                args.max_narration_speed,
            )

        audio, durations = prepare_audio(raw_audio, work, audio_speed)
        starts, ends = schedule(resolved_segments, durations, gap, args.initial_silence)
        if ends[-1] > target_duration - 0.2:
            raise ValueError(
                f"Final narration cue ends at {ends[-1]:.3f}s, too close to the "
                f"{target_duration:.3f}s output boundary"
            )

        srt = args.output.with_suffix(".srt")
        srt.write_text(build_subtitles(resolved_segments, starts, ends))

        mix = work / "narration.wav"
        inputs: list[str] = []
        filters: list[str] = []
        for index, (path, start) in enumerate(zip(audio, starts, strict=True)):
            inputs += ["-i", str(path)]
            filters.append(f"[{index}:a]adelay={round(start * 1000)}:all=1[a{index}]")
        filters.append(
            "".join(f"[a{index}]" for index in range(len(audio)))
            + f"amix=inputs={len(audio)}:normalize=0,apad,atrim=duration={target_duration:.6f}[aout]"
        )
        run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                *inputs,
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[aout]",
                str(mix),
            ],
            label="mix narration",
        )

        video = work / "video.mp4"
        if raw_duration > target_duration:
            video_filter = f"setpts=PTS/{video_speed:.10f},fps=30"
        else:
            video_filter = (
                f"tpad=stop_mode=clone:stop_duration={target_duration - raw_duration:.6f},fps=30"
            )
        run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(args.raw),
                "-vf",
                video_filter,
                "-an",
                "-t",
                f"{target_duration:.6f}",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                str(video),
            ],
            label="prepare video timeline",
        )

        subtitle_filter = (
            f"subtitles='{filter_path(srt)}':force_style='FontName=Arial,FontSize=11,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H90000000,BorderStyle=3,Outline=1,"
            "Shadow=0,MarginV=22'"
        )
        run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video),
                "-i",
                str(mix),
                "-vf",
                subtitle_filter,
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                f"{target_duration:.6f}",
                "-movflags",
                "+faststart",
                str(args.output),
            ],
            label="render MP4 with subtitles",
        )

        mkv = args.output.with_suffix(".mkv")
        if args.also_mkv:
            run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(video),
                    "-i",
                    str(mix),
                    "-i",
                    str(srt),
                    "-map",
                    "0:v",
                    "-map",
                    "1:a",
                    "-map",
                    "2:s",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-c:s",
                    "srt",
                    "-disposition:s:0",
                    "default",
                    "-metadata:s:s:0",
                    "language=eng",
                    "-metadata:s:a:0",
                    "language=eng",
                    "-t",
                    f"{target_duration:.6f}",
                    str(mkv),
                ],
                label="render MKV with selectable subtitles",
            )

        qa = args.output.parent / f"{args.output.stem}-qa"
        if qa.exists():
            shutil.rmtree(qa)
        qa.mkdir()
        sample_times = [
            min(start + args.qa_offset, max(start, end - 0.1), target_duration - 0.1)
            for index, (segment, start, end) in enumerate(
                zip(resolved_segments, starts, ends, strict=True)
            )
            if index == 0 or segment["anchor"] is not None
        ][:8]
        for index, sample_time in enumerate(sample_times, 1):
            run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{sample_time:.3f}",
                    "-i",
                    str(args.output),
                    "-frames:v",
                    "1",
                    str(qa / f"frame-{index:02d}.jpg"),
                ],
                label=f"extract QA frame {index}",
            )
        run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{target_duration - 0.2:.3f}",
                "-i",
                str(args.output),
                "-frames:v",
                "1",
                str(qa / "frame-final.jpg"),
            ],
            label="extract final QA frame",
        )
        contact_sheet = create_contact_sheet(qa, len(sample_times) + 1)

        probe = validate_media(args.output, target_duration)
        mean_volume, max_volume = detect_volume(args.output)
        if args.also_mkv:
            validate_media(mkv, target_duration, require_subtitles=True)

        print(f"Created: {args.output}")
        if args.also_mkv:
            print(f"Created: {mkv}")
        print(f"Subtitles: {srt}")
        print(f"QA contact sheet: {contact_sheet}")
        print(f"QA frames: {qa}")
        print(f"Raw/final duration: {raw_duration:.3f}s / {target_duration:.3f}s")
        print(f"Video speed: {video_speed:.3f}x")
        print(
            f"Narration speed: {audio_speed:.3f}x; gap: {gap:.2f}s; "
            f"final cue ends: {ends[-1]:.3f}s"
        )
        print(f"Audio volume: mean {mean_volume:.1f} dB; max {max_volume:.1f} dB")
        print(json.dumps(probe, indent=2))
        print("Media validation passed.")
    finally:
        if temporary:
            temporary.cleanup()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CommandError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
