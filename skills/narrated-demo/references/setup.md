# Setup

Use Python 3.10–3.13 (3.12 recommended) and a virtual environment. Commands below assume a POSIX
shell on macOS or Linux. Replace `SKILL_DIR` with the directory containing `SKILL.md`; do not
assume the skill was installed in a particular agent's configuration directory.

## System dependencies

Install ffmpeg/ffprobe with the `libx264` encoder and `subtitles` filter (libass), eSpeak NG for
Kokoro's pronunciation fallback, and libsndfile for WAV output.

macOS with Homebrew:

```bash
brew install ffmpeg espeak-ng libsndfile
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install ffmpeg espeak-ng libsndfile1
```

Verify your ffmpeg build; distribution packages differ:

```bash
ffmpeg -hide_banner -encoders 2>/dev/null | grep -E 'libx264|aac'
ffmpeg -hide_banner -filters 2>/dev/null | grep subtitles
ffprobe -version
```

Both encoders and the subtitle filter must be present. Have a font available for subtitles;
the builder requests Arial and libass uses a system fallback when it is not installed.

## Python environment

```bash
SKILL_DIR=/absolute/path/to/narrated-demo
python3 -m venv "$SKILL_DIR/.venv"
. "$SKILL_DIR/.venv/bin/activate"
python -m pip install -r "$SKILL_DIR/requirements.txt"
python -m unittest discover -s "$SKILL_DIR/tests" -v
```

Run helpers with this environment's Python, not whichever interpreter the agent normally uses.
A virtual environment outside the skill is equally valid; it need not be committed or distributed.
Requirements pin Kokoro, but do not lock every transitive dependency or bundle platform binaries.

## First voice run

```bash
python "$SKILL_DIR/scripts/kokoro_tts.py" \
  "The narration is ready." -o /absolute/path/to/output/voice-check.wav
```

The first synthesis can download Kokoro weights, voice data, and language resources from their
upstream hosts. Plan for several hundred megabytes or more, depending on existing Python/model
caches. Downloads need network access; subsequent synthesis runs locally with cached resources.
No TTS API key is needed. Listen to the WAV before recording a long demo.

The default is American English (`--lang a --voice af_heart`). Other Kokoro languages and voice
packs can need additional dependencies; consult [Kokoro's documentation](https://github.com/hexgrad/kokoro)
for setup. The bundled example uses English.

## Browser capability

No browser library is installed by `requirements.txt`. Use your agent's existing browser tools,
a locally installed recorder, or an existing video. Playwright, agent-browser, or a browser MCP
integration are options, not dependencies on a particular agent. Confirm video recording/export
is actually supported; screenshots alone do not establish that capability.

See [recording.md](recording.md) for the raw-video and timeline handoff. If no recording capability
is available, explain the missing requirement instead of claiming to have recorded a demo.
