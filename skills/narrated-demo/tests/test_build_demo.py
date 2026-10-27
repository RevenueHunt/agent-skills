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

    def test_subtitles_preserve_authored_phrase_and_line_boundaries(self) -> None:
        text = "The target is one shared parsing model,\nwith source positions,"
        self.assertEqual(build_demo.subtitle_text(text), text)
        self.assertEqual(build_demo.subtitle_text("It took 13 milliseconds."), "It took 13 milliseconds.")

    def test_paragraph_plans_fail_with_repair_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text(json.dumps({"segments": [{"text": "A whole paragraph. " * 20}]}))
            with self.assertRaisesRegex(ValueError, "Segment 1:.*42 characters"):
                build_demo.load_plan(plan)

    def test_three_lines_and_blank_lines_are_rejected(self) -> None:
        for text in ("First\nSecond\nThird", "First\n\nSecond"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "one or two non-empty"):
                build_demo.subtitle_text(text)

    def test_continuations_use_measured_duration_without_extra_gaps(self) -> None:
        segments = [
            {"anchor": 1.0, "text": "The target is one shared parsing model,\nwith source positions,"},
            {"anchor": None, "text": "and one owner for each quiz rule."},
            {"anchor": 7.0, "text": "Now inspect the result."},
        ]
        starts, ends = build_demo.schedule(segments, [4.0, 2.0, 2.0], gap=0.5, initial=0.8)
        self.assertEqual(starts, [1.0, 5.0, 7.5])
        self.assertEqual(ends, [5.0, 7.0, 9.5])
        self.assertEqual(
            build_demo.build_subtitles(segments, starts, ends),
            "1\n00:00:01,000 --> 00:00:05,000\n"
            "The target is one shared parsing model,\nwith source positions,\n\n"
            "2\n00:00:05,000 --> 00:00:07,000\nand one owner for each quiz rule.\n\n"
            "3\n00:00:07,500 --> 00:00:09,500\nNow inspect the result.\n",
        )

    def test_unreadable_speed_is_rejected_even_with_valid_line_lengths(self) -> None:
        with self.assertRaisesRegex(ValueError, "Subtitle 1 needs.*maximum 20"):
            build_demo.build_subtitles(
                [{"text": "The builder and compiler read\nthe same HTML differently."}], [0.0], [2.0]
            )

    def test_short_and_long_cues_require_reauthoring(self) -> None:
        for duration in (0.5, 8.0):
            with self.subTest(duration=duration), self.assertRaisesRegex(ValueError, "Merge.*split"):
                build_demo.build_subtitles([{"text": "Here is the result."}], [0.0], [duration])


if __name__ == "__main__":
    unittest.main()
