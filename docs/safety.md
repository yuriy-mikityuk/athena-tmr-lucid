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

Cue libraries must validate private sound-file availability before a sleep session.
Missing cue files should block the session plan rather than failing after the subject
is asleep.

Do not promise clinical benefit, diagnosis, treatment, or guaranteed lucid dreaming.

## Audio backend preflight

Real audio (`--backend system` or `--backend afplay`) requires an available
`afplay` command. Otherwise playback commands exit with code 2 and explain the
fix. Pilot 4/5 check this before connecting the source or creating recording files.
For intentional testing without sound, add `--allow-dry-run`; explicit
`--backend dry-run` and `--backend mock` also remain supported test modes.
This applies to `play-test-cue`, `train-tlr-cue`, `run-pilot4-cueing` and
`run-pilot5-full-night`.

For example: `muse-tmr play-test-cue --backend system --allow-dry-run` permits
silent fallback when `afplay` is missing. Metadata and reports preserve requested
and actual backend names; see [data_model.md](data_model.md#audio-backend-preflight).

Availability does not establish speaker routing or audibility. On the target Mac
with an available audio device, run `muse-tmr play-test-cue --backend system`
while awake and confirm sound through the intended output. This manual hardware
check remains required; silent testing cannot validate audible cues.
