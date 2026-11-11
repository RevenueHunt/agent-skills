from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "deck.py"
SPEC = importlib.util.spec_from_file_location("narrated_deck", MODULE_PATH)
assert SPEC and SPEC.loader
deck = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deck)


class DeckTests(unittest.TestCase):
    def test_parses_scenes_lines_and_front_matter(self) -> None:
        meta, scenes = deck.parse(
            "---\nspeed: 1.2\n---\n\n# Title\n\nIntro.\n\n> First line.\n\n## Points\n\n- a\n- b\n\n> Second.\n> Third.\n"
        )
        self.assertEqual(meta, {"voice": "af_heart", "speed": 1.2})
        self.assertEqual([s["title"] for s in scenes], ["Title", "Points"])
        self.assertEqual(scenes[1]["lines"], ["Second.", "Third."])
        self.assertEqual(scenes[1]["body"], "- a\n- b")

    def test_pronunciations_change_the_voice_but_not_the_captions(self) -> None:
        meta, scenes = deck.parse(
            "---\npronounce: Klaviyo=clay vee oh\n---\n\n# T\n\n"
            "> The JSON from Klaviyo, not JSONL.\n> Ask [Sidekick](side kick) about [Kokoro](/kˈOkəɹO/).\n"
        )
        self.assertNotIn("pronounce", meta)
        self.assertEqual(scenes[0]["lines"], ["The JSON from Klaviyo, not JSONL.", "Ask Sidekick about Kokoro."])
        self.assertEqual(
            scenes[0]["spoken"], ["The Jason from clay vee oh, not JSONL.", "Ask side kick about [Kokoro](/kˈOkəɹO/)."]
        )

    def test_names_every_slide_that_needs_a_fix(self) -> None:
        with self.assertRaises(deck.DeckError) as caught:
            deck.parse("# Silent\n\nNo narration.\n\n## Wordy\n\n> " + "word " * 25 + "\n")
        message = str(caught.exception)
        self.assertIn("scene 1 (Silent): no narration", message)
        self.assertIn("scene 2 (Wordy): line is", message)

    def test_bold_led_lists_become_stat_tiles(self) -> None:
        tiles = deck.body_html("- **30 days** nightly\n- **12 months** monthly")
        self.assertIn('<div class="stats n2">', tiles)
        self.assertIn("<b>30 days</b><span>nightly</span>", tiles)
        self.assertIn("<ul>", deck.body_html("- plain\n- **30** later"))
        # Bold labels stay a list (trial run: they became oversized tiles).
        self.assertIn("<ul>", deck.body_html("- **Setup** — once\n- **Run** — daily"))

    def test_narration_between_body_lines_reveals_the_slide_in_steps(self) -> None:
        _, scenes = deck.parse("## Plan\n\n- one\n\n> First.\n\n- two\n\n> Second.\n\n## Late\n\n- a\n- b\n\n> Only.\n> After.\n")
        plan, late = scenes
        # The list stays one tight list: the blank lines only framed the narration.
        self.assertEqual(plan["body"], "- one\n- two")
        self.assertEqual(plan["steps"], ["- one", "- one\n- two"])
        # Narration after the body shows the whole slide on every line, as before steps existed.
        self.assertEqual(late["steps"], [late["body"], late["body"]])
        step = deck.frame_html(plan, Path("/tmp"), "", plan["steps"][0])
        self.assertIn("<template class='step'>", step)
        self.assertNotIn("<template", deck.frame_html(plan, Path("/tmp"), "", plan["steps"][1]))

    def test_boxes_nest_carry_classes_and_leave_code_alone(self) -> None:
        page = deck.body_html(
            "::: row\n::: grow card soft\n**Before**\n\n- one\n:::\n::: grow\n```python\n:::\nx = 1\n```\n:::\n:::\n\n"
            "```mermaid\nflowchart LR\n  A:::accent --> B\n```",
            {"flowchart LR\n  A:::accent --> B": "<svg>drawn</svg>"},
        )
        self.assertIn('<div class="row">\n<div class="grow card soft">\n<p><strong>Before</strong></p>\n<ul>\n<li>one</li>', page)
        self.assertIn('</ul>\n</div>\n<div class="grow">\n<div class="hl">', page)
        self.assertIn('<span class="p">:::</span>', page)  # a ::: line inside code is code
        self.assertIn('<div class="diagram"><svg>drawn</svg></div>', page)
        self.assertEqual(page.count("<div"), page.count("</div>"))
        self.assertNotIn("markdown=", page)

    def test_unbalanced_boxes_name_the_slide(self) -> None:
        with self.assertRaises(deck.DeckError) as caught:
            deck.parse("## Open\n\n::: row\ntext\n\n> Spoken.\n\n## Stray\n\ntext\n:::\n\n> Spoken.\n")
        message = str(caught.exception)
        self.assertIn("scene 1 (Open): 1 box(es) opened with '::: class' never close", message)
        self.assertIn("scene 2 (Stray): a bare ':::' closes no box", message)

    def test_a_step_that_ends_inside_boxes_closes_them(self) -> None:
        _, scenes = deck.parse(
            "## Compare\n\n::: row\n::: grow\nBefore\n\n> First.\n\n:::\n::: grow\nAfter\n:::\n:::\n\n> Second.\n"
        )
        first = scenes[0]["steps"][0]
        self.assertEqual(first, "::: row\n::: grow\nBefore")
        self.assertEqual(deck.body_html(first), '<div class="row">\n<div class="grow">\n<p>Before</p>\n</div>\n</div>')

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_a_step_across_columns_shows_the_finished_layout(self) -> None:
        # Rendering only the step would give its one column the whole width; it must sit where the finished slide puts it.
        try:
            browser = deck.chrome()
        except deck.DeckError:
            self.skipTest("Chrome required")
        _, scenes = deck.parse(
            "## Compare\n\n::: row\n::: grow\n- left one\n- left two\n\n> First.\n\n:::\n::: grow\n- right\n:::\n:::\n\n> Second.\n"
        )
        css = deck.THEME.read_text()
        with tempfile.TemporaryDirectory() as tmp:
            gray = []
            for index, shown in enumerate(scenes[0]["steps"]):
                page = Path(tmp) / f"{index}.html"
                page.write_text(deck.frame_html(scenes[0], Path(tmp), css, shown))
                deck.screenshot(browser, page, Path(tmp) / f"{index}.jpg")
                gray.append(subprocess.run(
                    ["ffmpeg", "-loglevel", "error", "-i", str(Path(tmp) / f"{index}.jpg"), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                    check=True, capture_output=True,
                ).stdout)
        step, done = gray

        def differing(left: int, right: int) -> int:
            return sum(
                abs(step[y * deck.WIDTH + x] - done[y * deck.WIDTH + x]) > 40
                for y in range(0, deck.HEIGHT, 2) for x in range(left, right, 2)
            )

        self.assertEqual(differing(0, 960), 0)  # the left column, exactly where it ends up
        self.assertGreater(differing(960, deck.WIDTH), 100)  # the right column, not said yet

    def test_code_blocks_keep_their_hashes_and_quotes(self) -> None:
        # A `> ` line in a diff became narration and a `# ` comment a new slide (trial run of the example deck).
        _, scenes = deck.parse("## Diff\n\n```diff\n# header\n- > old\n+ > new\n```\n\n> Spoken.\n")
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0]["lines"], ["Spoken."])
        self.assertIn("+ > new", scenes[0]["body"])

    def test_code_is_highlighted_and_diagrams_become_their_svg(self) -> None:
        page = deck.body_html("```python\nx = 1\n```\n\n```mermaid\nflowchart TD\n  A --> B\n```", {"flowchart TD\n  A --> B": "<svg>drawn</svg>"})
        self.assertIn('<div class="hl">', page)
        self.assertIn('<div class="diagram"><svg>drawn</svg></div>', page)
        self.assertNotIn("flowchart", page)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_the_deck_plays_while_it_builds(self) -> None:
        published = self.build_stubbed("".join(f"## Slide {n}\n\n- point {n}\n\n> Line {n} a.\n> Line {n} b.\n\n" for n in range(4)))
        building, final = published[:-1], published[-1]
        self.assertEqual(building[0]["cues"], [])
        # The first line goes out alone, then the deck each time it has doubled, every part with audio of its length.
        self.assertEqual(len(building[1][0]["cues"]), 1)
        durations = [deck_json["duration"] for deck_json, _ in building[1:]]
        self.assertGreater(len(durations), 2)
        self.assertTrue(all(later >= 2 * earlier for earlier, later in zip(durations, durations[1:])), durations)
        for deck_json, audio_seconds in building[1:]:
            self.assertTrue(deck_json["building"])
            self.assertAlmostEqual(audio_seconds, deck_json["duration"], places=2)
        # The finished deck has exactly the shape decks had before they were published while building.
        self.assertEqual(list(final), ["title", "width", "height", "duration", "audio", "captions", "cues"])
        self.assertEqual(len(final["cues"]), 8)
        self.assertEqual(final["cues"][: len(building[-1][0]["cues"])], building[-1][0]["cues"])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_a_failed_build_keeps_what_it_published_and_says_why(self) -> None:
        published = self.build_stubbed("## One\n\n> First.\n> Second.\n> Third.\n", fail_on="Third.")
        self.assertEqual(published[-1]["error"], "Kokoro produced no audio for: Third.")
        self.assertNotIn("building", published[-1])
        # It stops at the first failure, keeping the part it had published, if any.
        self.assertIn([cue["text"] for cue in published[-1]["cues"]], [[], ["First."]])

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_a_failed_slide_stops_the_build_while_the_voice_still_loads(self) -> None:
        # Review of #23605: the build waited for each line's voice before looking at its slide.
        started = time.monotonic()
        published = self.build_stubbed("## One\n\n> First.\n", voice_loads_for=20, slide_fails=True)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(published[-1]["error"], "Chrome could not draw the slide")

    def build_stubbed(self, markdown: str, fail_on: str = "", voice_loads_for: float = 0, slide_fails: bool = False) -> list:
        """Build `markdown` with a stand-in voice (0.5 s per line) and Chrome; every deck.json published, a building
        one with its audio's length."""
        import soundfile as sf

        def voice(missing, meta, said):
            time.sleep(voice_loads_for)
            for path, line in missing.items():
                if line == fail_on:
                    error = deck.DeckError(f"Kokoro produced no audio for: {line}")
                    for future in said.values():
                        if not future.done():
                            future.set_exception(error)
                    return
                path.parent.mkdir(parents=True, exist_ok=True)
                sf.write(path, [0.0] * (deck.SR // 2), deck.SR)
                said[path].set_result(path)

        def screenshot(browser, page, out):
            if slide_fails:
                raise deck.DeckError("Chrome could not draw the slide")
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:s=64x36", "-frames:v", "1", str(out)],
                           check=True)

        published = []
        publish = deck.publish

        def record(out, manifest):
            publish(out, manifest)
            audio = out / manifest["audio"]
            published.append((manifest, sf.info(audio).duration) if manifest.get("building") and manifest["cues"] else manifest)

        originals = deck.voice, deck.screenshot, deck.publish, deck.chrome
        deck.voice, deck.screenshot, deck.publish, deck.chrome = voice, screenshot, record, lambda: "chrome"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / "talk.md"
                source.write_text(markdown)
                try:
                    deck.build(source, video=False)
                except deck.DeckError:
                    pass  # the failing build's own error, checked through what it published
        finally:
            deck.voice, deck.screenshot, deck.publish, deck.chrome = originals
        return published

    def test_slides_carry_no_spoken_text(self) -> None:
        # Captions are drawn by the player and the MP4's subtitle track, so one frame serves the whole scene.
        _, scenes = deck.parse("## Points\n\n- a\n\n> Spoken first.\n> Spoken second.\n")
        page = deck.frame_html(scenes[0], Path("/tmp"), "")
        self.assertIn("<h2>Points</h2>", page)
        self.assertNotIn("Spoken", page)


if __name__ == "__main__":
    unittest.main()
