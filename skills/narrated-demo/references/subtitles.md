# Subtitle authoring and timing

Read before writing a narration plan. This is an English landscape-demo profile, not a claim of
Netflix/BBC delivery compliance. For another language or aspect ratio, review its conventions first.

## Author meaning; validate mechanics

- One plan segment is one spoken cue. Prefer a complete short sentence; split long sentences at
  clauses or major phrase boundaries. Do not cut every N words or display an entire paragraph.
- A cue change and a line break are separate decisions. Within a cue, use one line when it fits,
  otherwise author one `\n` at a natural boundary. The builder preserves it; it does not guess grammar.
- Prefer punctuation, then clause/phrase boundaries. Keep articles/adjectives with nouns, names
  together, pronouns with verbs, auxiliaries/negation with verbs, and prepositions/conjunctions
  with the following phrase. Keep technical identifiers and number–unit pairs together.
- Prioritize linguistic coherence over equal line lengths. Avoid a lone trailing word. Do not add
  ellipses or dashes merely because a sentence continues into the next cue.
- Preserve the spoken words and their order. Rewrite narration and captions together if they are
  too dense. Do not silently abbreviate technical claims or omit qualifiers to pass validation.

## Example: one sentence across two cues

Poor: a fixed word count leaves “with” or “each” detached from the phrase that follows.

Better: two `segments`, with explicit line wrapping within the first cue:

```json
{
  "segments": [
    {"anchor": "shared-model", "text": "The target is one shared parsing model,\nwith source positions,"},
    {"text": "and one owner for each quiz rule."}
  ]
}
```

The anchor marks a visual phase, not every subtitle. Continuations have no anchor and no added
pacing gap. Layout newlines are removed before TTS so they do not split the utterance.

## Timing and readability

The script synthesizes each authored cue and uses its measured audio duration. There is no
character-proportional alignment and no new alignment dependency. Sentence fragments can affect
TTS prosody: prefer short complete sentences and check playback of continuations. Do not claim
word-level forced alignment; this is measured utterance-level timing.

Mechanical checks reject more than two lines, lines above 42 characters, cue durations outside
5/6–7 seconds, or reading speed above 20 characters/second (spaces and punctuation included;
layout newline counted as a space). Aim nearer 15–17 characters/second for technical diagrams;
that slower target is our editorial choice, not a universal standard. Allow time to inspect numbers
and visuals. If validation fails, merge very short cues, split long ones naturally, slow narration,
or rewrite it. Re-synthesize and re-measure; do not simply invent longer subtitle timestamps.

Keep subtitles in a stable clear area, normally bottom-center, with readable contrast. Character
limits do not guarantee rendered fit with proportional fonts. Inspect full-size frames for width,
UI overlap and legibility; never reduce font size just to fit a paragraph. The contact sheet samples
phase starts, not every cue: play through the video to inspect all cue transitions and speech sync.

## Sources

- [Netflix general requirements](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements): two lines, linguistic breaks, duration and positioning.
- [Netflix English (USA)](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide): 42 characters/line, 20 characters/second adult limit, continuity punctuation.
- [BBC subtitle guidelines](https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/): sentence/clause segmentation, linguistic priority, audio synchronization and extra reading time for complex visuals and figures.
