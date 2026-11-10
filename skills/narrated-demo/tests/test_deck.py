from __future__ import annotations

import importlib.util
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
        self.assertIn("class='ghost'", step)
        self.assertNotIn("ghost", deck.frame_html(plan, Path("/tmp"), "", plan["steps"][1]))

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

    def test_slides_carry_no_spoken_text(self) -> None:
        # Captions are drawn by the player and the MP4's subtitle track, so one frame serves the whole scene.
        _, scenes = deck.parse("## Points\n\n- a\n\n> Spoken first.\n> Spoken second.\n")
        page = deck.frame_html(scenes[0], Path("/tmp"), "")
        self.assertIn("<h2>Points</h2>", page)
        self.assertNotIn("Spoken", page)


if __name__ == "__main__":
    unittest.main()
