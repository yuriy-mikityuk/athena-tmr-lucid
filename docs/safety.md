# Safety

This project is for research tooling and personal experimentation. It is not a medical device.

Sleep-time audio must use conservative defaults:

- low maximum volume
- fade in and fade out
- cooldown between cues
- emergency stop
- arousal and motion checks
- no cueing outside a stable REM gate

`muse_tmr.audio.audio_player.AudioCuePlayer` enforces a maximum playback volume, records
the requested and effective volume, carries fade-in/fade-out settings, supports an
emergency stop state, and can append playback outcomes to JSONL logs. Tests must use
mock or dry-run playback rather than a real speaker.

Pre-sleep volume calibration must exist before planned sleep-time cues. Calibration
records the detectable, identifiable, and comfortable volume for the target playback
device. Cue scheduling should use the calibrated comfortable volume, bounded by the
session hard cap, and should block rather than cue when calibration is missing.

`muse_tmr.protocol.arousal_guard.ArousalGuard` evaluates motion, alpha, sudden HR
change, and artifact-quality proxies before scheduler decisions. Its conservative
defaults can lower volume, pause cueing with cooldown, or stop the session plan, and
each decision is JSONL-loggable for replay review.

On a preset without optics (`p21`) the guard is built with `optics_capable=False`,
like the REM gate. Missing PPG and heart rate is then not an artifact, so it does not
lower volume and does not count towards the `repeated_artifact_quality` pause, and the
two HR rules (`sudden_heart_rate_change`, `heart_rate_out_of_range`) are skipped
because there is no heart rate to judge. Every decision records
`ppg_absent_by_design` in its metadata. Before this, every `p21` night was paused from
the third epoch on and no cue could play. Motion, alpha and EEG artifact rules are
unchanged. On optics presets a PPG dropout still lowers volume and then pauses.

`muse-tmr run-pilot4-cueing` is the first command intended for sleep-time cueing.
It requires a volume calibration file, defaults to the non-audible `dry-run` backend,
and only uses real audio when an operator explicitly selects a backend such as
`system`. Its output directory includes scheduler, arousal, audio, awakening, and
emergency-stop artifacts for post-run review.

A night that asks for sound does not run silently by accident. `system` and `afplay`
need macOS `afplay`; when it is not on PATH, `run-pilot4-cueing`,
`run-pilot5-full-night`, `train-tlr-cue` and `play-test-cue` exit with code 2 and say
how to fix it, and the two night commands do so before they read an input, connect
the headband or write a file. `--allow-dry-run` runs silently on purpose, and the
night's `metadata.json` and summary record both the requested and the resolved
backend. Finding `afplay` does not prove the cue is audible through the intended
headphones; play a test cue while awake and listen.

Cue libraries must validate private sound-file availability before a sleep session.
Missing cue files should block the session plan rather than failing after the subject
is asleep.

Do not promise clinical benefit, diagnosis, treatment, or guaranteed lucid dreaming.
