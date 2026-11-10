#!/usr/bin/env python3
"""Turn a narrated Markdown deck into slide frames, one narration track and a deck.json player manifest.

    python deck.py my-talk.md            # -> my-talk.deck/deck.json, narration.m4a, frames/, contact.jpg, my-talk.srt
    python deck.py my-talk.md --video    # also my-talk.deck/my-talk.mp4, with the lines as a subtitle track

Source format: optional front matter (`voice`, `speed`), then one scene per `#`/`##` heading. A `#` heading is a
title slide; a `##` heading is a content slide whose body is ordinary Markdown, with highlighted code blocks,
```mermaid diagrams, `::: class` boxes (Pandoc's fenced divs, laid out by the theme's classes) and inline HTML. Every `> ` line in a scene is one spoken line and one caption, and shows the slide as written
above it: narration between body lines reveals the slide step by step. Captions are text, never pixels: the player
draws them over the slide and the MP4 carries them as a subtitle track. Spoken audio, diagrams and rendered frames are
cached by content, so editing one line re-voices that line and redraws nothing.
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
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
THEME = SKILL_DIR / "assets" / "deck.css"
WIDTH, HEIGHT = 1920, 1080
SR = 24_000  # Kokoro's output rate
LEAD, GAP_LINE, GAP_SCENE, TAIL = 0.6, 0.25, 0.7, 1.5
MAX_LINE = 90  # characters in one spoken line: two caption rows of 45
DEFAULTS = {"voice": "af_heart", "speed": 1.1}
CODE_STYLE = "github-dark"  # Pygments style for code blocks, on the theme's dark code background
# Mermaid draws ```mermaid blocks in Chrome. It is downloaded once, pinned and checked, like the voice model.
MERMAID_VERSION = "11.17.2"
MERMAID_URL = f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js"
MERMAID_SHA256 = "581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8"
MERMAID_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "narrated-demo"
# The theme's colours for diagrams and charts; authors never set colours. Sizes stay Mermaid's defaults, which every
# diagram type lays out for, and each drawing is scaled up by DIAGRAM_SCALE to read at 1920 wide.
DIAGRAM_SCALE = 1.8
MERMAID_CONFIG = {
    "startOnLoad": False,
    "theme": "base",
    "fontFamily": '"Inter", "Avenir Next", "Helvetica Neue", Arial, sans-serif',
    "themeVariables": {
        "primaryColor": "#f0ece2",
        "primaryBorderColor": "#0f3a44",
        "primaryTextColor": "#1c2427",
        "lineColor": "#5f6d70",
        "secondaryColor": "#f4e3d6",
        "tertiaryColor": "#fbfaf7",
        "clusterBkg": "#f4f1ea",
        "clusterBorder": "#d8d2c4",
        "edgeLabelBackground": "#fbfaf7",
        "noteBkgColor": "#f4e3d6",
        "noteBorderColor": "#d0743c",
        "actorBkg": "#f0ece2",
        "actorBorder": "#0f3a44",
        "signalColor": "#5f6d70",
        "pie1": "#d0743c", "pie2": "#0f3a44", "pie3": "#7a9ea3", "pie4": "#e8b48f", "pie5": "#4b5a5e", "pie6": "#c9d6d3",
        "pieOpacity": "1", "pieStrokeColor": "#fbfaf7", "pieStrokeWidth": "2px", "pieOuterStrokeWidth": "0px",
        "pieSectionTextColor": "#ffffff",
        "xyChart": {
            "backgroundColor": "#fbfaf7",
            "plotColorPalette": "#d0743c, #0f3a44, #7a9ea3, #e8b48f",
            "titleColor": "#0f3a44",
            "xAxisLabelColor": "#4b5a5e", "xAxisTitleColor": "#4b5a5e", "xAxisLineColor": "#5f6d70",
            "xAxisTickColor": "#5f6d70",
            "yAxisLabelColor": "#4b5a5e", "yAxisTitleColor": "#4b5a5e", "yAxisLineColor": "#5f6d70",
            "yAxisTickColor": "#5f6d70",
        },
    },
    "themeCSS": (
        ".node rect, .node polygon, rect.actor { rx: 10px; ry: 10px; stroke-width: 1.2px; } .flowchart-link { stroke-width: 1.6px; }"
        " .node.accent rect, .node.accent polygon, .node.accent path"
        " { fill: #f4e3d6 !important; stroke: #d0743c !important; stroke-width: 1.8px !important; }"
    ),
    "flowchart": {"curve": "basis"},
    "xyChart": {"width": 860, "height": 340},  # wide and short: a slide is wide, and the title takes the top
}
LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")
MERMAID_BLOCK = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
# A box is Pandoc's fenced div: `::: card soft` opens one with those classes, a bare `:::` closes it.
BOX_OPEN = re.compile(r"^ {0,3}:{3,}[ \t]*([A-Za-z][\w-]*(?:[ \t]+[A-Za-z][\w-]*)*)[ \t]*:*[ \t]*$")
BOX_CLOSE = re.compile(r"^ {0,3}:{3,}[ \t]*$")


class DeckError(Exception):
    pass


# ---------- parsing ----------


def box_lines(text: str):
    """Each line with what it does to boxes: ('open', classes), ('close', '') or ('text', line). Code blocks are text."""
    fenced = False
    for raw in text.splitlines():
        if raw.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and (opening := BOX_OPEN.match(raw)):
            yield "open", " ".join(opening[1].split())
            continue
        elif not fenced and BOX_CLOSE.match(raw):
            yield "close", ""
            continue
        yield "text", raw


def boxes(text: str) -> str:
    """`::: a b` … `:::` as <div class="a b" markdown="1"> … </div>, for md_in_html. Boxes still open at the end close
    there, so a step that stops inside a box is still whole."""
    out, depth = [], 0
    for kind, value in box_lines(text):
        if kind == "open":
            out += ["", f'<div class="{value}" markdown="1">', ""]
            depth += 1
        elif kind == "close" and depth:
            out += ["", "</div>", ""]
            depth -= 1
        else:
            out.append(value if kind == "text" else ":::")
    return "\n".join(out + ["", "</div>", ""] * depth)


def box_problem(body: str) -> str | None:
    depth = 0
    for kind, _ in box_lines(body):
        depth += {"open": 1, "close": -1}.get(kind, 0)
        if depth < 0:
            return "a bare ':::' closes no box; remove it, or open the box with '::: class'"
    if depth:
        return f"{depth} box(es) opened with '::: class' never close; end each with a line of only ':::'"
    return None


def parse(text: str) -> tuple[dict, list[dict]]:
    """Front matter and scenes: [{title, level, body, lines, steps}]; steps[i] is the body shown while lines[i] is spoken."""
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
    fenced = False  # inside a ``` block, where `#` and `>` are code, not slides or narration
    for raw in text.splitlines():
        heading = None if fenced else re.match(r"^(#{1,2})\s+(.*)$", raw)
        if heading:
            scenes.append({"level": len(heading[1]), "title": heading[2].strip(), "body": [], "lines": [], "marks": []})
        elif not scenes:
            if raw.strip():
                raise DeckError("text before the first # or ## heading; every slide starts with a heading")
        elif not fenced and raw.startswith(">"):
            line = raw[1:].strip()
            if line:
                scenes[-1]["lines"].append(line)
                scenes[-1]["marks"].append(len(scenes[-1]["body"]))
        else:
            if raw.lstrip().startswith("```"):
                fenced = not fenced
            scenes[-1]["body"].append(raw)
    if not scenes:
        raise DeckError("no scenes: start each slide with a # or ## heading")
    problems = []
    for number, scene in enumerate(scenes, 1):
        body, marks = scene["body"], scene.pop("marks")
        # A list read out item by item stays one tight list: drop the blank lines that only framed its narration,
        # or Markdown makes it a loose list and the spacing jumps between steps.
        for i in reversed(range(len(marks))):
            before = after = marks[i]
            while before and not body[before - 1].strip():
                before -= 1
            while after < len(body) and not body[after].strip():
                after += 1
            if before and after < len(body) and LIST_ITEM.match(body[before - 1]) and LIST_ITEM.match(body[after]):
                del body[before:after]
                marks = [before if before <= m <= after else m - (after - before) if m > after else m for m in marks]
        scene["steps"] = ["\n".join(body[:mark]).strip() for mark in marks]
        scene["body"] = "\n".join(body).strip()
        if not scene["lines"]:
            problems.append(f"scene {number} ({scene['title']}): no narration; add at least one '> ' line")
        if problem := box_problem(scene["body"]):
            problems.append(f"scene {number} ({scene['title']}): {problem}")
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


def body_html(markdown_text: str, diagrams: dict[str, str] | None = None) -> str:
    import markdown

    # Diagrams go in after Markdown, so it never sees their SVG.
    blocks: list[str] = []

    def stash(match: re.Match) -> str:
        blocks.append((diagrams or {}).get(match[1].strip(), ""))
        return f"\n\nDIAGRAM{len(blocks) - 1}\n\n"

    markdown_text = boxes(MERMAID_BLOCK.sub(stash, markdown_text))
    out = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code", "sane_lists", "codehilite", "md_in_html"],
        extension_configs={"codehilite": {"guess_lang": False, "css_class": "hl"}},
    )
    out = re.sub(r"<p>DIAGRAM(\d+)</p>", lambda m: f'<div class="diagram">{blocks[int(m[1])]}</div>', out)
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


def frame_html(scene: dict, base: Path, css: str, shown: str | None = None, diagrams: dict[str, str] | None = None) -> str:
    """One frame of a scene, showing `shown` (default: the whole body) where the whole slide would put it."""
    title = html.escape(scene["title"])
    kind = "cover" if scene["level"] == 1 else "content"

    def layer(body: str) -> str:
        if kind == "cover":
            return f"<h1>{title}</h1><div class='lede'>{body_html(body, diagrams)}</div>"
        return f"<h2>{title}</h2><div class='body'>{body_html(body, diagrams)}</div>"

    inner = layer(scene["body"])
    if shown is not None and shown != scene["body"]:
        # A step is the finished slide with what is not said yet hidden, so nothing moves while a slide builds, in
        # columns and cards too. The step's own render, never shown, says how much of the slide's text is out so far.
        inner += f"<template class='step'>{layer(shown)}</template>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><base href="{base.as_uri()}/">
<style>{css}</style></head><body>{SVG_DEFS}<main class="{kind}"><div class="fit">{inner}</div></main>
<script>
// Shrink the slide's content until it fits above the caption area, down to 60 %.
const main = document.querySelector('main'), fit = document.querySelector('.fit');
for (let s = 1; s > 0.6 && fit.scrollHeight * s > main.clientHeight; s -= 0.04) fit.style.zoom = s - 0.04;
const step = document.querySelector('template.step');
if (step) {{
  // Text and pictures in reading order; a picture or drawing counts as one.
  const parts = root => {{
    const found = [];
    const walk = node => {{
      for (const child of node.childNodes) {{
        if (child.nodeType === Node.TEXT_NODE) {{ if (child.data.trim()) found.push(child); }}
        else if (child.matches?.('img, svg')) found.push(child);
        else if (child.nodeType === Node.ELEMENT_NODE && !child.matches('style, script, template')) walk(child);
      }}
    }};
    walk(root);
    return found;
  }};
  const visible = new Set();
  for (const part of parts(fit).slice(0, parts(step.content).length))
    for (let node = part; node !== fit; node = node.parentNode) visible.add(node);
  for (const element of fit.querySelectorAll('*'))
    if (!element.parentElement.closest('svg')) element.style.visibility = visible.has(element) ? 'visible' : 'hidden';
}}
</script></body></html>"""


# Sideshow's arrowhead (see NOTICE): `marker-end="url(#arrow)"` ends a line in its own stroke colour.
SVG_DEFS = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs><marker id="arrow" viewBox="0 0 10 10"'
    ' refX="9" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">'
    '<path d="M0 0L10 5L0 10z" fill="context-stroke"/></marker></defs></svg>'
)


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


def run_chrome(browser: str, args: list[str], **options) -> subprocess.CompletedProcess:
    """Headless Chrome on a fresh profile. Now and then it exits with status 2 and the same run then works (seen on
    macOS in #21532, about one run in ten), so a failed run is retried once before the build stops."""
    for attempt in (1, 2):
        with tempfile.TemporaryDirectory() as profile:
            try:
                return subprocess.run(
                    [browser, "--headless", "--disable-gpu", "--allow-file-access-from-files", f"--user-data-dir={profile}",
                     f"--window-size={WIDTH},{HEIGHT}", *args],
                    check=True, capture_output=True, **options,
                )
            except subprocess.CalledProcessError:
                if attempt == 2:
                    raise


def screenshot(browser: str, page: Path, out: Path) -> None:
    png = out.with_suffix(".png")
    run_chrome(browser, ["--hide-scrollbars", f"--screenshot={png}", page.as_uri()])
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(png), "-q:v", "3", str(out)], check=True)
    png.unlink()


def code_css() -> str:
    from pygments.formatters import HtmlFormatter

    return HtmlFormatter(style=CODE_STYLE).get_style_defs(".body .hl")


def mermaid_js() -> Path:
    """The pinned Mermaid build, downloaded and checked on first use."""
    path = MERMAID_CACHE / f"mermaid-{MERMAID_VERSION}.min.js"
    if path.exists():
        return path
    print(f"downloading Mermaid {MERMAID_VERSION} (3.5 MB, once) to {path}", file=sys.stderr)
    try:
        with urllib.request.urlopen(MERMAID_URL, timeout=60) as response:
            data = response.read()
    except OSError as error:
        raise DeckError(f"diagrams need Mermaid, downloaded once from {MERMAID_URL}: {error}") from error
    if hashlib.sha256(data).hexdigest() != MERMAID_SHA256:
        raise DeckError(f"the Mermaid download from {MERMAID_URL} does not match its pinned checksum; not using it")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    partial.write_bytes(data)
    partial.replace(path)
    return path


def draw_diagrams(scenes: list[dict], cache: Path) -> dict[str, str]:
    """Every ```mermaid block as SVG in the theme, keyed by its source and cached by source and config."""
    config = json.dumps(MERMAID_CONFIG, sort_keys=True)
    drawn_by = MERMAID_VERSION + config + str(DIAGRAM_SCALE)
    wanted: dict[str, tuple[int, str]] = {}
    for number, scene in enumerate(scenes, 1):
        for match in MERMAID_BLOCK.finditer(scene["body"]):
            wanted.setdefault(match[1].strip(), (number, scene["title"]))
    paths = {
        source: cache / "diagrams" / (hashlib.sha256((source + drawn_by).encode()).hexdigest()[:20] + ".svg")
        for source in wanted
    }
    missing = [source for source, path in paths.items() if not path.exists()]
    if missing:
        # Each diagram's id is unique to it, so two on one slide keep their own styles.
        ids = ["d" + paths[source].stem for source in missing]
        # One Chrome run renders them all, and prints each SVG or Mermaid's error into the page for --dump-dom.
        page = f"""<!doctype html><html><head><meta charset="utf-8"></head><body><pre id="out"></pre>
<script src="{mermaid_js().as_uri()}"></script>
<script>
mermaid.initialize({config});
(async () => {{
  const results = [];
  const ids = {json.dumps(ids)};
  for (const [i, source] of {json.dumps(missing)}.entries()) {{
    try {{ results.push({{ svg: (await mermaid.render(ids[i], source)).svg }}); }}
    catch (error) {{ results.push({{ error: String(error && error.message || error) }}); }}
  }}
  document.getElementById('out').textContent = JSON.stringify(results);
}})();
</script></body></html>"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "diagrams.html"
            path.write_text(page)
            dom = run_chrome(chrome(), ["--virtual-time-budget=30000", "--dump-dom", path.as_uri()], text=True).stdout
        found = re.search(r'<pre id="out">(.*?)</pre>', dom, flags=re.S)
        if not found or not found[1]:
            raise DeckError("Mermaid did not finish drawing the diagrams in Chrome")
        problems = []
        for source, result in zip(missing, json.loads(html.unescape(found[1]))):
            if "error" in result:
                number, title = wanted[source]
                problems.append(f"scene {number} ({title}): Mermaid cannot draw this diagram: {result['error'].strip()}")
            else:
                paths[source].parent.mkdir(parents=True, exist_ok=True)
                svg = result["svg"]
                # Mermaid caps the drawing at its natural width; allow DIAGRAM_SCALE times that.
                width = re.search(r'<svg[^>]*?viewBox="[-\d.]+ [-\d.]+ ([\d.]+)', svg)
                if width:
                    svg = re.sub(r"max-width:\s*[\d.]+px", f"max-width: {float(width[1]) * DIAGRAM_SCALE:.0f}px", svg, count=1)
                paths[source].write_text(svg)
        if problems:
            raise DeckError("\n".join(problems))
    return {source: path.read_text() for source, path in paths.items()}


def render_frames(scenes: list[dict], base: Path, cache: Path) -> tuple[list[Path], int]:
    """One JPEG per spoken line (equal steps share one), cached by its HTML and images."""
    css = code_css() + THEME.read_text()  # the theme's own code rules come last and win
    diagrams = draw_diagrams(scenes, cache)
    jobs, frames = [], []
    for scene, shown in ((scene, shown) for scene in scenes for shown in scene["steps"]):
        page = frame_html(scene, base, css, shown, diagrams)
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
    for frame in set(frames):
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
        "captions": True,  # the player draws each cue's text; the frames carry none
        "cues": cues,
    }
    (out / "deck.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    contact_sheet(out, cues)

    print(f"{len(scenes)} scenes, {len(cues)} lines, {duration:.1f} s; voiced {voiced} new, drew {drawn} new")
    print(f"deck:    {out / 'deck.json'}")
    print(f"contact: {out / 'contact.jpg'}")
    if video:
        mp4 = out / f"{source.stem}.mp4"
        make_video(out, cues, duration, srt_path, mp4)
        print(f"video:   {mp4}")
    return out / "deck.json"


def contact_sheet(out: Path, cues: list[dict]) -> None:
    """Every slide on one image, as it looks at its last step, for agents that check the look without a player."""
    slides = [cue["image"] for i, cue in enumerate(cues) if i == len(cues) - 1 or cues[i + 1]["scene"] != cue["scene"]]
    columns = min(3, len(slides))
    inputs = [arg for image in slides for arg in ("-i", str(out / image))]
    pad = "".join(f"[{i}:v]scale=640:360[s{i}];" for i in range(len(slides)))
    layout = "|".join(f"{(i % columns) * 640}_{(i // columns) * 360}" for i in range(len(slides)))
    graph = (
        pad + "".join(f"[s{i}]" for i in range(len(slides))) + f"xstack=inputs={len(slides)}:layout={layout}:fill=white"
        if len(slides) > 1
        else "[0:v]scale=640:360"
    )
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph, "-frames:v", "1", str(out / "contact.jpg")],
        check=True,
    )


def make_video(out: Path, cues: list[dict], duration: float, srt: Path, mp4: Path) -> None:
    """The slides with the narration, and the spoken lines as a subtitle track players can turn on and off."""
    slides = [cue for i, cue in enumerate(cues) if i == 0 or cues[i - 1]["image"] != cue["image"]]
    ends = [cue["start"] for cue in slides[1:]] + [duration]
    listing = "".join(
        f"file '{out / cue['image']}'\nduration {end - cue['start']:.3f}\n" for cue, end in zip(slides, ends)
    ) + f"file '{out / slides[-1]['image']}'\n"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        handle.write(listing)
    try:
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", handle.name,
             "-i", str(out / "narration.m4a"), "-i", str(srt), "-map", "0:v", "-map", "1:a", "-map", "2:s",
             "-vf", "fps=25,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-tune", "stillimage", "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
             "-disposition:s:0", "default", "-shortest", "-movflags", "+faststart", str(mp4)],
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
