---
name: narrated-demo
description: Turn a document, README or report into a narrated slide deck (slides, voice, subtitles) that plays as a preview and can export an MP4; or narrate a screen recording of a web UI. Use when the user asks for an explainer, a narrated walkthrough, a video summary, a demo video or a screencast.
license: MIT
compatibility: Python 3.10–3.12 with kokoro, markdown, pygments and soundfile; ffmpeg; Google Chrome or Chromium. Setup in references/setup.md.
---

# Narrated decks

Write one Markdown file, run one command, get slides with a voice and captions. The theme, voice, timing and
caption style are fixed: do not restyle or tune them. Spend your effort on what the deck says.

## 1. Write the deck

Read the source document, pick the 4–8 points a newcomer needs, and write `<name>.md` next to where the user wants
the result. Every `#` or `##` heading starts a slide; the `> ` lines under it are spoken, one caption each.

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
- Images: `![](diagram.png)` with a path relative to the deck file. Tables render as they are.
- Front matter is optional; `af_heart` at `1.1` is the default English voice.

### Diagrams, code and step-by-step slides

- **Diagrams and charts:** a ` ```mermaid ` block becomes a diagram in the deck's colours: `flowchart LR` for a
  pipeline or a few boxes, `flowchart TD` with `subgraph`s for anything with layers, `sequenceDiagram` for who calls
  whom, `pie` and `xychart-beta` (`bar [...]`) for 2–6 numbers. Keep labels to a few words and at most about 8
  boxes; split a bigger system over two slides. Add `:::accent` to the one box the narration is about
  (`deck[deck.json]:::accent`). Never set colours or styles. A syntax error stops the build and names the slide.
- **Code:** tag every code block with its language (` ```python `, ` ```ts `, ` ```console `) so it is
  highlighted. Show a change as a ` ```diff ` block of a few lines. Mark the line the narration talks about with
  ` ```python hl_lines="3" `. At most about 8 lines per slide.
- **Step by step:** each `> ` line shows the slide as written above it. Put narration between body lines to build a
  slide while it is spoken: a list item by item, or a diagram after its introduction. Everything stays where it
  will be on the finished slide. Narration written after the whole body shows the whole slide from the start.

````markdown
## How a build runs

- Chrome draws every slide

> First, Chrome draws the slides.

- Each line is voiced

> Then every spoken line is voiced.

```mermaid
flowchart LR
  md[talk.md] --> deck[deck.json]:::accent --> mp4[MP4]
```

> Both meet in one deck, and an MP4 when you ask.
````

Do not write raw HTML or CSS in a deck: the look is fixed, and Markdown, diagrams and code cover what a slide needs.

## 2. Build and preview

```bash
python /absolute/path/to/narrated-demo/scripts/deck.py /absolute/path/to/<name>.md
```

It writes `<name>.deck/` beside the source: `deck.json` (the player manifest, with each line's text and start),
`narration.m4a`, one frame per slide and step, `contact.jpg` (every finished slide) and `<name>.srt`. The first deck
with a diagram downloads Mermaid once (3.5 MB, see [setup](references/setup.md)); after that it builds offline. Captions are text, never drawn
into the slides: the player shows them, and the bottom fifth of every slide stays empty for them. Lines and frames are
cached, so a re-run after an edit re-voices and redraws only what changed; it takes seconds. A problem (a line too long, a slide without
narration) stops it with a message naming the slide.

Check `contact.jpg` once: text fits, nothing is cut off, every slide says something. Fix the Markdown and re-run;
never edit the generated files. `<name>.deck/` is build output: do not commit or format it unless the user asks.

## 3. Deliver

- **In Ultimate:** link the deck's `deck.json` by its absolute path, `[My deck](/abs/path/<name>.deck/deck.json)`.
  The transcript shows it as a slide player with audio, captions (CC to hide them), slide skipping and YouTube's
  keys (Space, ←/→, F, C).
- **Anywhere else, or when the user asks for a video:** add `--video` to write `<name>.deck/<name>.mp4`, and report
  its path. The captions are a subtitle track players can turn on and off, not pixels.

Report the deck path, its duration (printed by the build), and anything you left out of the source document.

## Screen recordings

To narrate a recording of a real web UI in motion (a bug, a feature walkthrough), follow
[screen-demo](references/screen-demo.md) instead.
