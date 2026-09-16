# Browser recording and timelines

The media builder consumes ordinary files. It does not communicate with a browser tool or coding
agent. Use any recorder that produces an ffmpeg-readable video and can identify visible phase times.

## File handoff

Keep three inputs in a task-specific output directory:

- `raw.webm` (or MP4/another ffmpeg-readable format): finalized browser video.
- `narration.json`: a non-empty `segments` array, each with `text` and optional `anchor`.
- `timeline.json`: a `markers` object mapping phase names to raw-video seconds.

Example narration:

```json
{
  "segments": [
    {"anchor": "overview", "text": "First, review the starting state."},
    {"anchor": "result", "text": "Now the result is ready."}
  ]
}
```

Example timeline shape (replace these times with observed values):

```json
{
  "markers": {"overview": 1.1, "result": 10.3}
}
```

Named markers use **raw-video time**, and are adjusted if `--duration` speeds up the video.
Numeric anchors instead refer to **final-output time**. An omitted anchor follows the preceding
narration with the selected pacing gap. Named markers are less error-prone for browser journeys.

The builder uses only `markers` from the timeline; extra diagnostic fields are optional and are
not interpreted as proof that browser checks passed. Unknown marker names fail the build.

## Recording sequence

1. Use a fresh isolated browser context, a 1440×900 viewport, and disposable application state.
   Use an authenticated profile only when requested; never copy profile files into the output.
2. Verify the initial frame and close unrelated UI. Set up page-error collection before the
   journey if the browser tool supports it.
3. Start recording to a **new** take path. Establish the recorder's video time origin.
4. For each phase, perform real interactions and assert the intended visible state. Record its
   marker only once the state is visibly settled, then hold it long enough for the narration.
5. Stop/finalize the recording in guaranteed cleanup, including when an interaction fails. Some
   recorders only flush the file when the browser context closes. Follow that recorder's API.
6. Inspect the recorder's completion status and verify the saved video has a decodable stream.
   A file that merely exists, an elapsed timeout, or a screenshot is not proof of a complete take.
7. Save the timeline and browser diagnostics separately from any unverified assumptions.

Keep interactions and recording in the **same session**. Batch actions when supported to avoid
unnecessary tool-call delays, but assert states rather than relying only on fixed sleeps. Respect
your tool's own limits; this skill imposes no agent-specific call budget or result schema.

## Establishing accurate markers

Use recorder timestamps when available. Otherwise inspect the finalized raw video to locate each
settled phase, and record those observed times. A host or page clock is useful only after its
offset to the raw video's start is established: timing from after a `start recording` call returns
can be wrong because the recorder may already have captured frames. Navigation can also reset a
page clock. Do not present guessed elapsed times as measured video markers.

Extract candidate frames to check transitions (replace paths and time):

```bash
ffmpeg -hide_banner -loglevel error -ss 8.4 -i /path/to/raw.webm \
  -frames:v 1 /path/to/phase-check.jpg
```

Use multiple nearby frames when the exact transition is uncertain. After building, inspect the
rendered contact sheet as well: earlier speech can delay a phase beyond its marker. The builder
pads only the final frame, not intermediate screens. Shorten narration or lengthen screen holds
if a cue extends into the next phase.

## Controlled fixtures versus real applications

For a synthetic explanatory fixture, page-side choreography is acceptable, provided the visible
states are verified and the result is labeled illustrative. The bundled example is such a fixture.

For claims about actual application behavior, use real pointer/keyboard interactions and assert
postconditions. Calling page functions or editing the DOM does not prove that a real user can
complete that journey. Do not perform production, destructive, purchase, or account/privacy
changes without explicit authorization.

## Failure and diagnostics

- Failed interaction or interrupted recording: treat the take as suspect and use a new path.
- Unplayable or truncated file: fix recorder finalization before building narration.
- Wrong narration screen: fix markers, narration length, or screen holds; do not just guess offsets.
- No explicit browser-error check: report **not checked**, not zero errors.
- Local URL unavailable: verify the server before opening a fresh browser session.

Browser errors and media validation are separate checks. Successful ffmpeg output says nothing
about application correctness or whether browser diagnostics were collected.
