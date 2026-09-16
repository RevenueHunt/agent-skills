from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "build_demo.py"
SPEC = importlib.util.spec_from_file_location("narrated_demo_build", MODULE_PATH)
assert SPEC and SPEC.loader
build_demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_demo)


class NarratedDemoBuildTests(unittest.TestCase):
    def test_plan_accepts_marker_names_and_numeric_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "segments": [
                            {"anchor": "bug", "text": "Show the bug."},
                            {"anchor": 12.5, "text": "Explain the fix."},
                        ]
                    }
                )
            )
            segments = build_demo.load_plan(plan)

        self.assertEqual(segments[0]["anchor"], "bug")
        self.assertEqual(segments[1]["anchor"], 12.5)

    def test_marker_timestamps_follow_video_speed(self) -> None:
        segments = [{"anchor": "fix", "text": "The fix."}]
        resolved = build_demo.resolve_anchors(segments, {"fix": 20.0}, video_speed=2.0)
        self.assertEqual(resolved[0]["anchor"], 10.0)
        self.assertEqual(resolved[0]["marker"], "fix")

    def test_missing_marker_is_actionable(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing timeline marker 'summary'"):
            build_demo.resolve_anchors(
                [{"anchor": "summary", "text": "Summary."}], {}, video_speed=1.0
            )

    def test_narration_speed_limit_fails_instead_of_over_accelerating(self) -> None:
        segments = [{"anchor": 8.0, "text": "Long ending."}]
        with self.assertRaisesRegex(ValueError, "1.10x narration-speed limit"):
            build_demo.choose_audio_speed(
                segments,
                durations=[8.0],
                gap=0.5,
                initial=0.8,
                target=12.0,
                max_speed=1.10,
            )

    def test_duration_accepts_auto_or_seconds(self) -> None:
        self.assertIsNone(build_demo.parse_requested_duration("auto"))
        self.assertEqual(build_demo.parse_requested_duration("42.5"), 42.5)
        with self.assertRaisesRegex(ValueError, "greater than one"):
            build_demo.parse_requested_duration("1")

    def test_schedule_preserves_markers_without_overlapping_speech(self) -> None:
        segments = [{"anchor": 1.0}, {"anchor": 2.0}, {"anchor": 10.0}]
        starts, ends = build_demo.schedule(segments, [3.0, 2.0, 1.0], gap=0.5, initial=0.8)
        self.assertEqual(starts, [1.0, 4.5, 10.0])
        self.assertEqual(ends, [4.0, 6.5, 11.0])

    def test_numeric_anchors_are_output_times(self) -> None:
        segments = [{"anchor": 4.0, "text": "The result."}]
        self.assertEqual(build_demo.resolve_anchors(segments, {}, video_speed=2.0), segments)

    def test_timeline_accepts_plain_and_wrapped_marker_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "timeline.json"
            for payload in ({"overview": 1.2}, {"markers": {"overview": 1.2}}):
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload))
                    self.assertEqual(build_demo.load_timeline(path), {"overview": 1.2})

    def test_empty_narration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps({"segments": [{"text": "  "}]}))
            with self.assertRaisesRegex(ValueError, "empty text"):
                build_demo.load_plan(path)

    def test_subtitles_are_bounded_to_three_lines(self) -> None:
        text = " ".join(["word"] * 60)
        self.assertLessEqual(len(build_demo.subtitle_text(text).splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
