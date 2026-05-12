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
