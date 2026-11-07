#!/usr/bin/env python3
"""Turn a narrated Markdown deck into slide frames, one narration track and a deck.json player manifest.

    python deck.py my-talk.md            # -> my-talk.deck/deck.json, narration.m4a, frames/, contact.jpg, my-talk.srt
    python deck.py my-talk.md --video    # also my-talk.deck/my-talk.mp4

Source format: optional front matter (`voice`, `speed`), then one scene per `#`/`##` heading. A `#` heading is a
title slide; a `##` heading is a content slide whose body is ordinary Markdown. Every `> ` line in a scene is one
spoken line and one subtitle. Spoken audio and rendered frames are cached by content, so editing one line re-voices
that line and redraws only its frame.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
THEME = SKILL_DIR / "assets" / "deck.css"
WIDTH, HEIGHT = 1920, 1080
SR = 24_000  # Kokoro's output rate
LEAD, GAP_LINE, GAP_SCENE, TAIL = 0.6, 0.25, 0.7, 1.5
MAX_LINE = 90  # characters in one spoken line: two subtitle rows of 45
DEFAULTS = {"voice": "af_heart", "speed": 1.1}


class DeckError(Exception):
    pass


# ---------- parsing ----------


def parse(text: str) -> tuple[dict, list[dict]]:
    """Front matter and scenes: [{title, level, body, lines}]."""
    meta = dict(DEFAULTS)
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end < 0:
            raise DeckError("front matter starts with --- but never ends")
        for raw in text[4:end].splitlines():
            if ":" in raw:
                key, value = raw.split(":", 1)
                meta[key.strip()] = value.strip().strip("\"'")
        text = text[end + 4 :]
    meta["speed"] = float(meta["speed"])
    scenes: list[dict] = []
    for raw in text.splitlines():
        heading = re.match(r"^(#{1,2})\s+(.*)$", raw)
        if heading:
            scenes.append({"level": len(heading[1]), "title": heading[2].strip(), "body": [], "lines": []})
        elif not scenes:
            if raw.strip():
                raise DeckError("text before the first # or ## heading; every slide starts with a heading")
        elif raw.startswith(">"):
            line = raw[1:].strip()
            if line:
                scenes[-1]["lines"].append(line)
        else:
            scenes[-1]["body"].append(raw)
    if not scenes:
        raise DeckError("no scenes: start each slide with a # or ## heading")
    problems = []
    for number, scene in enumerate(scenes, 1):
        scene["body"] = "\n".join(scene["body"]).strip()
        if not scene["lines"]:
            problems.append(f"scene {number} ({scene['title']}): no narration; add at least one '> ' line")
        for line in scene["lines"]:
            if len(line) > MAX_LINE:
                problems.append(
                    f"scene {number} ({scene['title']}): line is {len(line)} characters, over {MAX_LINE}; "
                    f"split it into two '> ' lines: {line[:60]}…"
                )
    if problems:
        raise DeckError("\n".join(problems))
    return meta, scenes


# ---------- slides ----------


def body_html(markdown_text: str) -> str:
    import markdown

    out = markdown.markdown(markdown_text, extensions=["tables", "fenced_code", "sane_lists"])
    # A list whose every item opens with a bold number becomes a row of stat tiles: "- **328 ha** official area".
    # Bold labels ("**Setup** — …") stay a list: as tiles they wrap into huge headings.
    def stats(match: re.Match) -> str:
        items = re.findall(r"<li>(.*?)</li>", match[1], flags=re.S)
        if items and all(re.match(r"\s*<strong>[\d$€£~<>+−-]", item) for item in items):
            tiles = "".join(
                f'<div class="stat"><b>{m[1]}</b><span>{m[2].strip(" —–-:")}</span></div>'
                for m in (re.match(r"\s*<strong>(.*?)</strong>(.*)", item, flags=re.S) for item in items)
            )
            return f'<div class="stats n{min(len(items), 4)}">{tiles}</div>'
        return match[0]

    return re.sub(r"<ul>\n?(.*?)</ul>", stats, out, flags=re.S)


def frame_html(scene: dict, line: str, base: Path, css: str) -> str:
    title = html.escape(scene["title"])
    kind = "cover" if scene["level"] == 1 else "content"
    inner = (
        f"<h1>{title}</h1><div class='lede'>{body_html(scene['body'])}</div>"
        if kind == "cover"
        else f"<h2>{title}</h2><div class='body'>{body_html(scene['body'])}</div>"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><base href="{base.as_uri()}/">
<style>{css}</style></head><body><main class="{kind}"><div class="fit">{inner}</div></main>
<footer><p>{html.escape(line)}</p></footer>
<script>
// Shrink the slide's content until it fits above the subtitle band, down to 60 %.
const main = document.querySelector('main'), fit = document.querySelector('.fit');
for (let s = 1; s > 0.6 && fit.scrollHeight * s > main.clientHeight; s -= 0.04) fit.style.zoom = s - 0.04;
</script></body></html>"""


def chrome() -> str:
    for candidate in (
        os.environ.get("CHROME"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    raise DeckError("no Chrome or Chromium found; set CHROME=/path/to/chrome")


def screenshot(browser: str, page: Path, out: Path) -> None:
    png = out.with_suffix(".png")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(
            [browser, "--headless", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
             f"--user-data-dir={profile}", f"--window-size={WIDTH},{HEIGHT}", f"--screenshot={png}", page.as_uri()],
            check=True, capture_output=True,
        )
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(png), "-q:v", "3", str(out)], check=True)
    png.unlink()


def render_frames(scenes: list[dict], base: Path, cache: Path) -> tuple[list[Path], int]:
    """One JPEG per spoken line (its slide with that line as subtitle), cached by its HTML and images."""
    css = THEME.read_text()
    jobs, frames = [], []
    for scene in scenes:
        for line in scene["lines"]:
            page = frame_html(scene, line, base, css)
            assets = "".join(
                f"{p}:{(base / p).stat().st_mtime_ns}"
                for p in re.findall(r'src="([^":]+)"', page)
                if (base / p).exists()
            )
            digest = hashlib.sha256((page + assets).encode()).hexdigest()[:20]
            out = cache / "frames" / f"{digest}.jpg"
            frames.append(out)
            if not out.exists() and all(out != job[1] for job in jobs):
                jobs.append((page, out))
    if jobs:
        (cache / "frames").mkdir(parents=True, exist_ok=True)
        browser = chrome()
        with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(6) as pool:
            pages = []
            for index, (page, out) in enumerate(jobs):
                path = Path(tmp) / f"{index}.html"
                path.write_text(page)
                pages.append((path, out))
            list(pool.map(lambda job: screenshot(browser, *job), pages))
    return frames, len(jobs)


# ---------- voice ----------


def voice(scenes: list[dict], meta: dict, cache: Path) -> tuple[list[Path], int]:
    """One WAV per spoken line, cached by text, voice and speed."""
    lines = [line for scene in scenes for line in scene["lines"]]
    paths = [
        cache / "audio" / (hashlib.sha256(json.dumps([line, meta["voice"], meta["speed"]]).encode()).hexdigest()[:20] + ".wav")
        for line in lines
    ]
    missing = [(line, path) for line, path in zip(lines, paths) if not path.exists()]
    if missing:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline

        (cache / "audio").mkdir(parents=True, exist_ok=True)
        pipeline = KPipeline(lang_code=meta["voice"][0], repo_id="hexgrad/Kokoro-82M")
        for line, path in missing:
            chunks = [np.asarray(a, dtype=np.float32) for _, _, a in pipeline(line, voice=meta["voice"], speed=meta["speed"])]
            if not chunks:
                raise DeckError(f"Kokoro produced no audio for: {line}")
            sf.write(path, np.concatenate(chunks), SR)
    return paths, len(missing)


# ---------- assembly ----------


def timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def build(source: Path, video: bool) -> Path:
    import numpy as np
    import soundfile as sf

    meta, scenes = parse(source.read_text())
    out = source.with_suffix(".deck")
    cache = out / ".cache"
    frames, drawn = render_frames(scenes, source.parent.resolve(), cache)
    audio, voiced = voice(scenes, meta, cache)

    cues, pieces, srt = [], [np.zeros(int(LEAD * SR), np.float32)], []
    t, index = LEAD, 0
    for number, scene in enumerate(scenes):
        for position, line in enumerate(scene["lines"]):
            speech = sf.read(audio[index], dtype="float32")[0]
            last_in_scene = position == len(scene["lines"]) - 1
            gap = TAIL if last_in_scene and number == len(scenes) - 1 else GAP_SCENE if last_in_scene else GAP_LINE
            length = len(speech) / SR
            start = 0.0 if index == 0 else t  # the first frame shows during the lead-in too
            cues.append({"scene": number, "text": line, "image": f"frames/{frames[index].name}", "start": round(start, 3)})
            srt.append(f"{index + 1}\n{timestamp(t)} --> {timestamp(t + length)}\n{textwrap.fill(line, 45)}\n")
            pieces += [speech, np.zeros(int(gap * SR), np.float32)]
            t += length + gap
            index += 1
    duration = round(t, 3)

    (out / "frames").mkdir(parents=True, exist_ok=True)
    for old in (out / "frames").iterdir():
        old.unlink()
    for frame in frames:
        shutil.copyfile(frame, out / "frames" / frame.name)
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "narration.wav"
        sf.write(wav, np.concatenate(pieces), SR)
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "96k", str(out / "narration.m4a")],
            check=True,
        )
    srt_path = out / f"{source.stem}.srt"
    srt_path.write_text("\n".join(srt))
    manifest = {
        "title": scenes[0]["title"],
        "width": WIDTH,
        "height": HEIGHT,
        "duration": duration,
        "audio": "narration.m4a",
        "cues": cues,
    }
    (out / "deck.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    contact_sheet(out, cues)

    print(f"{len(scenes)} scenes, {len(cues)} lines, {duration:.1f} s; voiced {voiced} new, drew {drawn} new")
    print(f"deck:    {out / 'deck.json'}")
    print(f"contact: {out / 'contact.jpg'}")
    if video:
        mp4 = out / f"{source.stem}.mp4"
        make_video(out, cues, duration, mp4)
        print(f"video:   {mp4}")
    return out / "deck.json"


def contact_sheet(out: Path, cues: list[dict]) -> None:
    """The first frame of every scene on one image, for agents that check the look without a player."""
    firsts = [cue["image"] for i, cue in enumerate(cues) if i == 0 or cues[i - 1]["scene"] != cue["scene"]]
    columns = min(3, len(firsts))
    inputs = [arg for image in firsts for arg in ("-i", str(out / image))]
    pad = "".join(f"[{i}:v]scale=640:360[s{i}];" for i in range(len(firsts)))
    layout = "|".join(f"{(i % columns) * 640}_{(i // columns) * 360}" for i in range(len(firsts)))
    graph = (
        pad + "".join(f"[s{i}]" for i in range(len(firsts))) + f"xstack=inputs={len(firsts)}:layout={layout}:fill=white"
        if len(firsts) > 1
        else "[0:v]scale=640:360"
    )
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph, "-frames:v", "1", str(out / "contact.jpg")],
        check=True,
    )


def make_video(out: Path, cues: list[dict], duration: float, mp4: Path) -> None:
    ends = [cue["start"] for cue in cues[1:]] + [duration]
    listing = "".join(
        f"file '{out / cue['image']}'\nduration {end - cue['start']:.3f}\n" for cue, end in zip(cues, ends)
    ) + f"file '{out / cues[-1]['image']}'\n"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write(listing)
    try:
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", handle.name,
             "-i", str(out / "narration.m4a"), "-vf", "fps=25,format=yuv420p", "-c:v", "libx264",
             "-preset", "medium", "-crf", "20", "-tune", "stillimage", "-c:a", "copy", "-shortest",
             "-movflags", "+faststart", str(mp4)],
            check=True,
        )
    finally:
        os.unlink(handle.name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a narrated slide deck from Markdown")
    parser.add_argument("source", type=Path, help="the deck's Markdown file")
    parser.add_argument("--video", action="store_true", help="also write an MP4")
    args = parser.parse_args()
    try:
        build(args.source.resolve(), args.video)
    except DeckError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
