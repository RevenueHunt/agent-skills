---
name: narrated-demo
description: Create a narrated screen-capture demo of a web UI with local voiceover and subtitles. Use when the user asks for a video, screencast, narrated walkthrough, feature demo, or bug explanation. Works with any browser recorder and coding agent with file and shell access.
license: MIT
compatibility: Requires Python 3.10–3.13, Audio8 Realistic 0.6B (torch + transformers<5), ffmpeg/ffprobe with libx264 and libass, and a browser recorder or existing recording. First-time TTS setup needs network access. Setup documented for macOS and Linux.
---

# Narrated screen demos

Produce an H.264/AAC MP4 with burned-in subtitles, an SRT, and optionally an MKV with selectable
subtitles. Use the agent's available file, shell, browser, and image-inspection capabilities;
no tool names, agent runtime, or fixed installation directory are required. Deliver the video as a
local file and open it in VLC. Do not upload or embed it in Sideshow; that is for text and static
representations, not video delivery in this workflow.

Resolve all relative paths below against **the directory containing this SKILL.md**, not the
user's project. Keep recordings and build caches in a separate output directory.

## 1. Preflight

Read [setup](references/setup.md). Use the configured Python environment and run:

```bash
python -m unittest discover -s /absolute/path/to/narrated-demo/tests -v
python /absolute/path/to/narrated-demo/scripts/audio8_tts.py \
  "Narration check." -o /absolute/path/to/output/narration-check.wav
```

Confirm ffmpeg/ffprobe, subtitle support, and a browser recording capability before proceeding.
The bundled builder always uses Audio8 Realistic 0.6B with the bundled reference voice
(`assets/voice-reference.wav`), so every video has the same realistic voice. If it is unavailable,
report the blocker rather than silently substituting a different voice engine. Ask before installing dependencies or downloading models
when the user's environment requires approval.

## 2. Storyboard and narration

Read [subtitle authoring and timing](references/subtitles.md) before writing narration.
Create 3–7 visual phases, each with a settled state and marker. Each `segments` entry is one short
spoken subtitle cue, not a whole phase or paragraph. Anchor only the first cue of each phase;
omit `anchor` on continuations. Author natural sentence/clause boundaries and explicit `\n` line
breaks: at most two lines of 42 characters each (English profile). Aim for 125–150 spoken words/minute.

```json
{
  "segments": [
    {"anchor": "overview", "text": "The builder and compiler read\nthe same HTML differently."},
    {"text": "That means two interpretations\nto keep in agreement."},
    {"anchor": "change", "text": "Now both use the compiler's tree."},
    {"text": "Each quiz rule has one owner."},
    {"anchor": "completed", "text": "The old bridge can then be deleted."}
  ]
}
```

Each cue is synthesized once; its measured audio duration determines subtitle timing. Check cadence
when a sentence spans cues; rewrite awkward fragments rather than adding arbitrary gaps. Legacy
paragraph plans must be re-authored, not sliced by word count or timed by text length. Allow enough
screen time for every cue in a phase plus a small gap. Prefer markers over guessed timestamps.
See the [synthetic example](examples/README.md) for a safe practice surface.

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

Defaults: Audio8 Realistic 0.6B (bundled voice), 0.5-second gaps between visual phases (no added gaps between continuation
cues), and automatic duration. The helper reuses cached speech and pads the **final** video frame
instead of speeding narration. It rejects cues outside 0.83–7 seconds or above 20 characters/second.
It does not freeze intermediate screens: markers are earliest start times, and earlier speech can
delay later cues. If narration and screens diverge, shorten the text or re-record with longer holds.

Use `--duration <seconds>` only for an explicit duration requirement. Speech cannot exceed 1.15×
by default; shorten narration or increase duration rather than forcing unnatural speed.

## 5. QA and delivery

The build must finish with `Media validation passed.` Then:

1. Inspect `demo-qa/contact-sheet.jpg` and any questionable individual frames.
2. Confirm each narration phase matches the screen and the final frame is useful. Check natural
   subtitle breaks, rendered width and speech sync, especially numbers and sentence continuations.
   Reserve a stable subtitle area in fixtures; do not cover focal controls or shrink text to fit prose.
3. After validation, open the final MP4 in VLC: on macOS, use `open -a VLC "/absolute/path/demo.mp4"`;
   on Linux, use `vlc "/absolute/path/demo.mp4"`. For revisions, open the newly generated file, not
   the previous version. Play it with audio; if VLC or playback is unavailable, report the limitation
   and local path rather than substituting Sideshow.
4. Report the MP4/SRT/optional MKV paths, VLC opening result, exact duration, narration speed, what
   it demonstrates, browser diagnostics, and any unverified checks.
5. Stop only processes started for this task. Remove only task-created disposable fixtures and
   unwanted takes; preserve requested deliverables and reusable caches.

Never expose credentials, customer data, or private tabs in a demo. Use disposable/local state.
Recording is not permission to publish, purchase, or mutate production. Keep those actions subject
to explicit authorization. A synthetic fixture is illustrative, not proof of real-app behavior.
