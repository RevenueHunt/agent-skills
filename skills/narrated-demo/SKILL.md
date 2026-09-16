---
name: narrated-demo
description: Create a narrated screen-capture demo of a web UI with local voiceover and subtitles. Use when the user asks for a video, screencast, narrated walkthrough, feature demo, or bug explanation. Works with any browser recorder and coding agent with file and shell access.
license: MIT
compatibility: Requires Python 3.10–3.13, Kokoro, ffmpeg/ffprobe with libx264 and libass, and a browser recorder or existing recording. First-time TTS setup needs network access. Setup documented for macOS and Linux.
---

# Narrated screen demos

Produce an H.264/AAC MP4 with burned-in subtitles, an SRT, and optionally an MKV with selectable
subtitles. Use the agent's available file, shell, browser, and image-inspection capabilities;
no tool names, agent runtime, or fixed installation directory are required.

Resolve all relative paths below against **the directory containing this SKILL.md**, not the
user's project. Keep recordings and build caches in a separate output directory.

## 1. Preflight

Read [setup](references/setup.md). Use the configured Python environment and run:

```bash
python -m unittest discover -s /absolute/path/to/narrated-demo/tests -v
python /absolute/path/to/narrated-demo/scripts/kokoro_tts.py \
  "Narration check." -o /absolute/path/to/output/narration-check.wav
```

Confirm ffmpeg/ffprobe, subtitle support, and a browser recording capability before proceeding.
The bundled builder uses Kokoro; if it is unavailable, report the blocker rather than silently
substituting a different voice engine. Ask before installing dependencies or downloading models
when the user's environment requires approval.

## 2. Storyboard and narration

Create 3–7 short phases, each with a settled visible state and a marker name. Aim for roughly
125–150 spoken words per minute. Save a narration plan:

```json
{
  "segments": [
    {"anchor": "overview", "text": "Here is the starting workflow."},
    {"anchor": "change", "text": "Next, we make the change."},
    {"anchor": "completed", "text": "Finally, the result is ready."}
  ]
}
```

Allow enough screen time for each sentence plus a small gap. Marker names are preferred over
guessed timestamps. See the [synthetic example](examples/README.md) for a safe practice surface.

## 3. Record and capture markers

Read [recording and timeline requirements](references/recording.md). Use the available browser
recorder, or an existing recording from the user; consult that tool's own API rather than assuming
particular command names. Default to a fresh isolated session, 1440×900 viewport, and one take.

Verify the starting frame, use stable selectors and state assertions, record transitions, then
finalize the recording even if an interaction fails. Save observed marker times in `timeline.json`:

```json
{"markers": {"overview": 0.8, "change": 8.4, "completed": 17.2}}
```

Those numbers illustrate the format, not timings to reuse. Times are seconds from the raw video's
start. Verify the finalized file can be decoded. Use explicit browser diagnostics if available;
otherwise report page errors as **not checked**, never zero.

## 4. Build

```bash
python /absolute/path/to/narrated-demo/scripts/build_demo.py \
  --raw /absolute/path/to/output/raw.webm \
  --plan /absolute/path/to/output/narration.json \
  --timeline /absolute/path/to/output/timeline.json \
  --output /absolute/path/to/output/demo.mp4 \
  --pacing tight --also-mkv \
  --work-dir /absolute/path/to/output/build-cache
```

Defaults: Kokoro `af_heart`, 0.5-second narration gaps, and automatic duration. The helper reuses
cached speech and pads the **final** video frame instead of speeding narration. It does not freeze
intermediate screens: markers are earliest start times, and earlier speech can delay later cues.
If narration and screens diverge, shorten the text or re-record with longer holds.

Use `--duration <seconds>` only for an explicit duration requirement. Speech cannot exceed 1.15×
by default; shorten narration or increase duration rather than forcing unnatural speed.

## 5. QA and delivery

The build must finish with `Media validation passed.` Then:

1. Inspect `demo-qa/contact-sheet.jpg` and any questionable individual frames.
2. Confirm each narration phase matches the screen, subtitles avoid focal controls, and the final
   frame is useful. Play the MP4 with audio; if playback is unavailable, disclose that limitation.
3. Report the MP4/SRT/optional MKV paths, exact duration, narration speed, what it demonstrates,
   browser diagnostics, and any unverified checks.
4. Stop only processes started for this task. Remove only task-created disposable fixtures and
   unwanted takes; preserve requested deliverables and reusable caches.

Never expose credentials, customer data, or private tabs in a demo. Use disposable/local state.
Recording is not permission to publish, purchase, or mutate production. Keep those actions subject
to explicit authorization. A synthetic fixture is illustrative, not proof of real-app behavior.
