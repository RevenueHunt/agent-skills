"""Exercise rendering with generated media; no TTS packages or model download needed."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_build_demo import build_demo


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class MediaTests(unittest.TestCase):
    def test_build_renders_padded_video_subtitles_and_qa(self) -> None:
        with tempfile.TemporaryDirectory(prefix="narrated demo ") as directory:
            work = Path(directory)
            raw = work / "raw.mp4"
            audio = work / "speech.wav"
            plan = work / "plan.json"
            timeline = work / "timeline.json"
            output = work / "demo.mp4"
            build_demo.run([
                "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                "color=c=navy:s=320x200:r=30:d=1", "-c:v", "libx264", str(raw),
            ])
            build_demo.run([
                "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=1", str(audio),
            ])
            plan.write_text(json.dumps({"segments": [{"anchor": "overview", "text": "Media validation fixture."}]}))
            timeline.write_text(json.dumps({"markers": {"overview": 0.8}}))
            argv = [
                "build_demo.py", "--raw", str(raw), "--plan", str(plan),
                "--timeline", str(timeline), "--output", str(output), "--also-mkv",
                "--work-dir", str(work / "cache"),
            ]
            log = io.StringIO()
            with (
                patch.object(sys, "argv", argv),
                patch.object(build_demo, "prepare_raw_narration", return_value=([audio], [1.0])),
                contextlib.redirect_stdout(log),
            ):
                self.assertEqual(build_demo.main(), 0)

            self.assertIn("Media validation passed.", log.getvalue())
            self.assertGreater(build_demo.probe_duration(output), build_demo.probe_duration(raw))
            build_demo.validate_media(output, 2.3)
            build_demo.validate_media(output.with_suffix(".mkv"), 2.3, require_subtitles=True)
            self.assertIn("00:00:00,800 --> 00:00:01,800", output.with_suffix(".srt").read_text())
            self.assertGreater((work / "demo-qa" / "contact-sheet.jpg").stat().st_size, 0)
            self.assertTrue((work / "demo-qa" / "frame-final.jpg").is_file())
            pixel_format = build_demo.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=pix_fmt", "-of", "csv=p=0", str(output),
            ]).stdout.strip()
            self.assertEqual(pixel_format, "yuv420p")

    def test_silent_audio_fails_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            silent = Path(directory) / "silent.wav"
            build_demo.run([
                "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                "anullsrc=r=44100:cl=mono", "-t", "0.3", str(silent),
            ])
            with self.assertRaises(ValueError):
                build_demo.detect_volume(silent)


if __name__ == "__main__":
    unittest.main()
