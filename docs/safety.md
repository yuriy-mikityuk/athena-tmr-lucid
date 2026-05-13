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

`muse-tmr run-pilot4-cueing` is the first command intended for sleep-time cueing.
It requires a volume calibration file, defaults to the non-audible `dry-run` backend,
and only uses real audio when an operator explicitly selects a backend such as
`system`. Its output directory includes scheduler, arousal, audio, awakening, and
emergency-stop artifacts for post-run review.

Cue libraries must validate private sound-file availability before a sleep session.
Missing cue files should block the session plan rather than failing after the subject
is asleep.

Do not promise clinical benefit, diagnosis, treatment, or guaranteed lucid dreaming.
