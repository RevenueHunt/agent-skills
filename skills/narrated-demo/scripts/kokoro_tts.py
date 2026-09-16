#!/usr/bin/env python3
"""Kokoro-82M text-to-speech helpers and CLI.

The reusable ``synthesize_many`` function initializes Kokoro once for a group of
segments. The CLI preserves the original single-segment interface.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


SynthesisRequest = tuple[str, Path]


def synthesize_many(
    requests: Sequence[SynthesisRequest],
    *,
    voice: str = "af_heart",
    lang: str = "a",
    speed: float = 1.0,
) -> None:
    """Synthesize all requests with one loaded Kokoro pipeline."""
    if not requests:
        return

    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
    except ImportError as exc:
        requirements = Path(__file__).resolve().parent.parent / "requirements.txt"
        raise RuntimeError(
            f'Missing TTS dependency: {exc}. In your virtual environment, run: '
            f'python -m pip install -r "{requirements}"'
        ) from exc

    pipeline = KPipeline(lang_code=lang)
    for text, output in requests:
        chunks = [
            np.asarray(audio, dtype=np.float32)
            for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed)
        ]
        if not chunks:
            raise RuntimeError(f"Kokoro produced no audio for {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, np.concatenate(chunks), 24_000)


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize one Kokoro-82M WAV file")
    parser.add_argument("text", help="Text to speak")
    parser.add_argument("-o", "--out", type=Path, required=True, help="Output WAV path")
    parser.add_argument("--voice", default="af_heart", help="Voice pack, for example af_heart")
    parser.add_argument("--lang", default="a", help="Kokoro language code")
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()

    try:
        synthesize_many(
            [(args.text, args.out)],
            voice=args.voice,
            lang=args.lang,
            speed=args.speed,
        )
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
