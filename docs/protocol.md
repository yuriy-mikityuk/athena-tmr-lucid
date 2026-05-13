# Protocol Notes

The project aims to preserve key REM-TMR/TLR protocol controls:

- pre-sleep puzzle assignment
- cued-vs-uncued randomization
- unique cue metadata per puzzle
- optional TLR block before puzzle cues
- REM-gated cue playback
- arousal and motion guardrails
- morning dream report and puzzle retest
- explicit analysis of limitations

Cue metadata lives in `muse_tmr.audio.cue_library` and should be validated before a
session starts. Protocol layers should reference cue IDs from a validated catalog
rather than hard-coded file paths.

Protocol settings start in `configs/protocol_konkoly_like.yaml` and should be versioned with each session.

## Pre-Sleep Puzzle Sessions

Puzzle session management lives in `muse_tmr.protocol.puzzle_protocol`. It is the M5
foundation for later cued-vs-uncued randomization and REM-gated scheduling.

The puzzle catalog stores:

- puzzle ID, prompt, solution, and cue ID
- solved, known, and retired flags
- tags/source metadata
- timed pre-sleep attempts

Night sessions are generated from eligible unsolved tasks. By default, eligibility
excludes solved, known, and retired tasks, then selects four tasks. Passing a seed makes
selection reproducible.

## Cued Vs Uncued Randomization

`muse_tmr.protocol.randomization` assigns the generated night-session puzzle IDs into
cued and uncued groups. The default split cues half of the session tasks, uses a seed
for reproducibility, and saves a versioned JSON assignment.

The assignment exposes `scheduled_puzzle_ids`, which is intentionally identical to the
cued group. Scheduler code must use this field or `scheduled_cue_ids()` rather than
iterating over every puzzle in the night session. Calling `ensure_schedulable()` on an
uncued puzzle raises an error, making accidental scheduling of control tasks a tested
contract.

Association checks compare a remembered response with the expected solution using a
case-insensitive whitespace-normalized match and append the result to the night session
metadata.

Private catalogs and generated sessions should stay under gitignored locations such as
`data/protocol/`.
