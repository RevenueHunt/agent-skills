# RevenueHunt Agent Skills

Practical skills for coding agents. Plain Markdown instructions, small command-line helpers,
no required agent SDK, plugin, or MCP server.

## Narrated demos

[`narrated-demo`](skills/narrated-demo/SKILL.md) turns a browser recording and a short narration
plan into a shareable video:

- Local Kokoro-82M voiceover, cached between builds.
- Narration anchored to observed screen transitions.
- H.264/AAC MP4 with burned-in subtitles, plus SRT and optional soft-subtitle MKV.
- Natural-speed narration by default, media validation, and visual QA frames.

Use it for feature walkthroughs, bug explanations, and before/after demos. It is a workflow for
an agent, not a hosted video service or a one-command recorder for arbitrary websites.

[Download a 31.8-second synthetic example](https://github.com/RevenueHunt/agent-skills/releases/download/v0.1.0/narrated-demo.mp4).

## Use with your agent

The skill follows the [Agent Skills format](https://agentskills.io/specification). Use it with
Claude Code, Codex, Pi, or another coding agent that can read files and run commands. Native skill
discovery varies by agent; the workflow does not depend on native discovery or any named tool API.

```bash
git clone https://github.com/RevenueHunt/agent-skills.git
```

Either copy the **entire** `skills/narrated-demo` directory into your agent's documented skill
location, or keep the checkout anywhere and give your agent this prompt:

> Read `/absolute/path/to/agent-skills/skills/narrated-demo/SKILL.md` and follow it to make a
> narrated walkthrough of [local URL and journey]. Save the result to [output directory].
> Use disposable test data and do not publish the video.

The agent needs shell/file access and a way to capture the browser, such as Playwright,
agent-browser, a browser MCP tool with recording support, or a recording supplied by you.
A screenshot-only browser tool is not sufficient for a continuous recording. The media builder
accepts any recording ffmpeg can decode; no particular browser integration is required.

## Setup and first demo

1. Follow [setup](skills/narrated-demo/references/setup.md) for Python and system dependencies.
2. Try the [synthetic example](skills/narrated-demo/examples/README.md); it has no accounts,
   customer data, external assets, or production actions.
3. Inspect the generated contact sheet and play the final MP4 before sharing it.

Python 3.10–3.13 is required by the current Kokoro dependency. Setup instructions target macOS
and Linux; Windows is not currently validated. Agent-agnostic does not mean dependency-free.
Kokoro downloads model/language resources on first use, then synthesizes locally. No paid TTS
API or API key is required. Your coding agent's own data handling still applies.

## Tests

From the repository root:

```bash
python3 -m unittest discover -s skills/narrated-demo/tests -v
```

Pure unit tests need only Python. Media tests additionally require ffmpeg/ffprobe with libx264,
AAC, and libass subtitle support. They use generated audio rather than downloading a TTS model;
they validate the media pipeline, not voice quality. CI runs both on Linux.

## Safety and limitations

- Record isolated test state. Do not include credentials, browser profiles, customer information,
  or private URLs in public examples or artifacts.
- Recording, installing a skill, and publishing a video are separate permissions.
- Markers control the earliest narration start; they do not pause the video between phases.
  Leave sufficient screen time, and verify alignment after rendering.
- The skill documents a portable workflow; it does not claim end-to-end certification in every
  agent or browser integration.

## License and dependencies

Our skill instructions, helpers, and fixture are [MIT licensed](LICENSE).
[Kokoro code](https://github.com/hexgrad/kokoro) and
[model weights](https://huggingface.co/hexgrad/Kokoro-82M) are Apache-2.0 licensed and are downloaded
separately. ffmpeg, its codecs, Python dependencies, and browser tools retain their own licenses.
No model weights, browser binaries, or real application recordings are bundled.
