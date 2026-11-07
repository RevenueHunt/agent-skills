---
name: narrated-demo
description: Turn a document, README or report into a narrated slide deck (slides, voice, subtitles) that plays as a preview and can export an MP4; or narrate a screen recording of a web UI. Use when the user asks for an explainer, a narrated walkthrough, a video summary, a demo video or a screencast.
license: MIT
compatibility: Python 3.10–3.12 with kokoro, markdown and soundfile; ffmpeg; Google Chrome or Chromium. Setup in references/setup.md.
---

# Narrated decks

Write one Markdown file, run one command, get slides with a voice and subtitles. The theme, voice, timing and
subtitle style are fixed: do not restyle or tune them. Spend your effort on what the deck says.

## 1. Write the deck

Read the source document, pick the 4–8 points a newcomer needs, and write `<name>.md` next to where the user wants
the result. Every `#` or `##` heading starts a slide; the `> ` lines under it are spoken, one subtitle each.

```markdown
---
voice: af_heart
speed: 1.1
---

# Nightly backups

What runs every night, and how to get a file back.

> Every night, the server copies your files somewhere safe.
> Here is what it keeps, and how to restore one.

## How it works

1. At 2 AM a snapshot of `/data` is taken
2. Only changed blocks are uploaded
3. A check reads every snapshot back

> At two in the morning, it takes a snapshot of the data folder.
> Only the parts that changed are uploaded.
> Then it reads the snapshot back, to prove it is complete.

## What it keeps

- **30 days** of nightly snapshots
- **12 months** of monthly ones

> You can go back to any night in the last thirty days.
> After that, one snapshot per month is kept for a year.
```

Rules that keep it watchable:

- **Slides carry key words; narration carries sentences.** At most 5 bullets or a 4-row table per slide. A list
  whose every item starts with a bold number (`- **30 days** of snapshots`) becomes stat tiles; use them for 2–4
  key figures, never for bold labels.
- **One idea per spoken line**, at most 90 characters; aim for 2–4 lines per slide and 1–2 minutes in all.
- **Write narration the way it is said.** Spell out symbols and units the voice would misread ("150 MB" →
  "a hundred and fifty megabytes", "v2" → "version two"); plain numbers are fine.
- Images: `![](diagram.png)` with a path relative to the deck file. Code blocks and tables render as they are.
- Front matter is optional; `af_heart` at `1.1` is the default English voice.

## 2. Build and preview

```bash
python /absolute/path/to/narrated-demo/scripts/deck.py /absolute/path/to/<name>.md
```

It writes `<name>.deck/` beside the source: `deck.json` (the player manifest), `narration.m4a`, one frame per
spoken line, `contact.jpg` (the first frame of each slide) and `<name>.srt`. Lines and frames are cached, so a re-run
after an edit re-voices and redraws only what changed; it takes seconds. A problem (a line too long, a slide without
narration) stops it with a message naming the slide.

Check `contact.jpg` once: text fits, nothing is cut off, every slide says something. Fix the Markdown and re-run;
never edit the generated files. `<name>.deck/` is build output: do not commit or format it unless the user asks.

## 3. Deliver

- **In Ultimate:** link the deck's `deck.json` by its absolute path, `[My deck](/abs/path/<name>.deck/deck.json)`.
  The transcript shows it as a slide player with audio, subtitles and slide skipping.
- **Anywhere else, or when the user asks for a video:** add `--video` to write `<name>.deck/<name>.mp4`, and report
  its path.

Report the deck path, its duration (printed by the build), and anything you left out of the source document.

## Screen recordings

To narrate a recording of a real web UI in motion (a bug, a feature walkthrough), follow
[screen-demo](references/screen-demo.md) instead.
