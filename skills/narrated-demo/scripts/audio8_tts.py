#!/usr/bin/env python3
"""Audio8 Realistic 0.6B text-to-speech helpers and CLI.

Every cue is cloned from one bundled reference clip (``assets/voice-reference.wav``,
the model's own default voice), so a whole video keeps one voice. The reusable
``synthesize_many`` loads the model once for a group of cues.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

MODEL = "Edge0/Audio8-TTS-Realistic-0.6b"
SKILL_DIR = Path(__file__).resolve().parent.parent
VOICE = SKILL_DIR / "assets" / "voice-reference.wav"
VOICE_TEXT = (
    "The morning rain has finally stopped, and sunlight is spilling through the window. "
    "Let's take a short walk before we start the rest of our day."
)
SEEDS = (42, 7, 1234)  # a cue that never reaches end-of-speech is retried with the next seed

SynthesisRequest = tuple[str, Path]


def synthesize_many(requests: Sequence[SynthesisRequest]) -> None:
    """Synthesize all requests with one loaded Audio8 model."""
    if not requests:
        return
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    try:
        import soundfile as sf
        import torch
        from transformers import AutoModel, AutoProcessor
    except ImportError as exc:
        requirements = SKILL_DIR / "requirements.txt"
        raise RuntimeError(
            f'Missing TTS dependency: {exc}. In your virtual environment, run: '
            f'python -m pip install -r "{requirements}"'
        ) from exc

    device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True)
    model = AutoModel.from_pretrained(MODEL, trust_remote_code=True, dtype=torch.float32).eval().to(device)
    sample_rate = int(model.config.codec_sample_rate)

    for text, output in requests:
        inputs = processor(
            text=[text], reference_audio=[VOICE], reference_text=[VOICE_TEXT], return_tensors="pt"
        )
        inputs = {key: value.to(device) for key, value in inputs.items()}
        for seed in SEEDS:
            generator = torch.Generator(device=device).manual_seed(seed)
            with torch.inference_mode():
                result = model.generate(
                    **inputs, max_new_tokens=1024, temperature=0.8, top_p=0.95, top_k=50,
                    do_sample=True, generator=generator, return_dict_in_generate=True,
                )
                waveform, lengths = model.decode_audio(result.codes)
            if bool(result.finished[0]):
                break
        else:
            raise RuntimeError(f"Audio8 never finished speaking {text!r}; shorten or rephrase the cue")
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, waveform[0, : int(lengths[0])].float().cpu().numpy(), sample_rate)


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize one Audio8 Realistic 0.6B WAV file")
    parser.add_argument("text", help="Text to speak")
    parser.add_argument("-o", "--out", type=Path, required=True, help="Output WAV path")
    args = parser.parse_args()
    try:
        synthesize_many([(args.text, args.out)])
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
