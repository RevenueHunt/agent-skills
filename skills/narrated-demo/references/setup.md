# Setup

Use Python 3.10–3.13 (3.12 recommended) and a virtual environment. Commands below assume a POSIX
shell on macOS or Linux. Replace `SKILL_DIR` with the directory containing `SKILL.md`; do not
assume the skill was installed in a particular agent's configuration directory.

## System dependencies

Install ffmpeg/ffprobe with the `libx264` encoder and `subtitles` filter (libass), and libsndfile
for WAV output.

macOS with Homebrew:

```bash
brew install ffmpeg-full libsndfile
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install ffmpeg libsndfile1
```

Verify your ffmpeg build; distribution packages differ:

```bash
ffmpeg -hide_banner -encoders 2>/dev/null | grep -E 'libx264|aac'
ffmpeg -hide_banner -filters 2>/dev/null | grep subtitles
ffprobe -version
```

Both encoders and the subtitle filter must be present. Homebrew's regular `ffmpeg` may lack
libass; `ffmpeg-full` is keg-only, so select its `bin` directory on PATH as above. Have a font available
for subtitles; the builder requests Arial and libass uses a system fallback when it is not installed.

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
Requirements pin `transformers<5` (Audio8's remote code needs 4.x), but do not lock every transitive dependency or bundle platform binaries.

## First voice run

```bash
python "$SKILL_DIR/scripts/audio8_tts.py" \
  "The narration is ready." -o /absolute/path/to/output/voice-check.wav
```

The first synthesis downloads `Edge0/Audio8-TTS-Realistic-0.6b` (about 2.4 GB, Apache-2.0) from
Hugging Face into `~/.cache/huggingface`. Downloads need network access; subsequent synthesis runs locally with cached resources.
No TTS API key is needed. Listen to the WAV before recording a long demo.

Every cue is cloned from `assets/voice-reference.wav` (the model's own default voice; its transcript
is `VOICE_TEXT` in `scripts/audio8_tts.py`), so all cues share one voice. It runs on the Mac GPU
(MPS, with `PYTORCH_ENABLE_MPS_FALLBACK=1` set by the script), CUDA, or CPU. Expect roughly 1.3 s of
compute per second of speech on an M2 Max, so a 5-minute script takes about 7 minutes the first time;
the build cache reuses cues afterwards. A cue that never reaches end-of-speech is retried with
another seed, then fails: shorten or rephrase it. Output is 44.1 kHz mono. English is tested.

## Browser capability

No browser library is installed by `requirements.txt`. Use your agent's existing browser tools,
a locally installed recorder, or an existing video. Playwright, agent-browser, or a browser MCP
integration are options, not dependencies on a particular agent. Confirm video recording/export
is actually supported; screenshots alone do not establish that capability.

See [recording.md](recording.md) for the raw-video and timeline handoff. If no recording capability
is available, explain the missing requirement instead of claiming to have recorded a demo.
