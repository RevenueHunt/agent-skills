# Synthetic walkthrough

A small, self-contained practice page: no external assets, authentication, customer data, or
production mutations. Its three states match `narration.json`. It is an illustration, not a
RevenueHunt product UI or a test of application behavior.

## Record

After [setup](../references/setup.md), ask your coding agent:

> Read this skill's SKILL.md. Open examples/index.html in an isolated browser. Record the starting
> state, click Apply update, then click Finish demo. Hold each settled phase for roughly ten
> seconds. Use examples/narration.json for the voiceover, derive timeline markers from the actual
> recording, and build and inspect the final video. Label this a synthetic fixture.

Open the HTML directly with a `file://` URL when supported. If your browser tool requires HTTP,
serve **only this examples directory** on localhost:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory /absolute/path/to/narrated-demo/examples
```

Visit `http://127.0.0.1:8765/`. Stop your server after recording. Do not expose the broader checkout
or use a public tunnel. The page does not advance on its own: the agent should use actual buttons.

Follow [recording.md](../references/recording.md) to produce:

- `raw.webm` or another finalized recording;
- `timeline.json` containing the observed `overview`, `change`, and `completed` markers.

Do not copy nominal ten-second intervals into the timeline as though they were measured.

## Build

With the setup environment activated:

```bash
SKILL_DIR=/absolute/path/to/narrated-demo
OUTPUT_DIR=/absolute/path/to/output
python "$SKILL_DIR/scripts/build_demo.py" \
  --raw "$OUTPUT_DIR/raw.webm" \
  --plan "$SKILL_DIR/examples/narration.json" \
  --timeline "$OUTPUT_DIR/timeline.json" \
  --output "$OUTPUT_DIR/demo.mp4" \
  --also-mkv --work-dir "$OUTPUT_DIR/build-cache"
```

The raw file's extension need not be WebM; pass the path your recorder actually produced.
Inspect the contact sheet, check narration against the three visible states, and play the MP4.
Generated videos, caches, and QA frames are deliberately not source files in this repository.
