# FAQ

Answers to what has come up in the issues, mostly #108, #112, #160 and #167. Dated 2026-10-23. Figures and their sources are in [`numbers.md`](numbers.md).

## How accurate is the REM detection?

Nobody knows yet. The only figures come from one EEG-only night, `overnight_20260707` on `p21`, scored against GSSC, an automated stager, not against PSG or a human scorer. The `p21` gate thresholds were tuned on that night and reported on the same night, so they are in-sample. Against GSSC the gate reached a binary REM-vs-not κ of 0.30 with precision 0.30 and recall 0.80 ([PR #115](https://github.com/yuriy-mikityuk/remind-eeg/pull/115)). That κ is not comparable with the five-class κ of sleep-staging papers, such as the vendor's 0.76 for Muse-S against PSG.

GSSC itself was trained mostly on C3, C4, F3, F4 from NSRR PSG, and there is no published evaluation of it on forehead-only EEG like the Muse AF7/AF8. Earlier versions of the code called the `p21` pair `VALIDATED` and GSSC `frontal-trained`; both words were dropped for that reason. Getting a real reference needs nights scored against PSG or by a person, tracked in [#116](https://github.com/yuriy-mikityuk/remind-eeg/issues/116).

## Why is the gate so strict on `p21`?

Two things happened on the same night ([#112](https://github.com/yuriy-mikityuk/remind-eeg/issues/112)). First the gate never opened at all: `p21` streams no optics, so the missing heart rate capped the gate's confidence at 0.55, below the 0.70 it needed to open. Since #114 the gate knows when a preset has no optics by design. Then, once it could open, it was open for 724 of 960 epochs, about 75 % of the night, because the heuristic detector runs hot (mean `P_REM` 0.82). Raising the thresholds to 0.90/0.85 brought that down to about 36 % ([PR #115](https://github.com/yuriy-mikityuk/remind-eeg/pull/115)). The detector itself is effectively one feature: against GSSC only `low_delta_power` separates REM ([#116](https://github.com/yuriy-mikityuk/remind-eeg/issues/116)). Reweighting it will change the thresholds again.

## Why does the night preset skip heart rate?

Battery ([#108](https://github.com/yuriy-mikityuk/remind-eeg/issues/108)). With the optics on (`p1034`) the headband drained at 23.34 %/h, about 4.3 h on a charge, and the first overnight attempt died after about 2 h 29 min. Without them (`p21`) it drained at 10.01 %/h on a bench test and 10.60 %/h over a full 8 h night. REM is densest late in the night, so a recording that dies at 4 h misses most of it. The cost is that the detector loses its heart-rate features on `p21`.

## How soon after REM starts can a cue play?

Not before 60 to 90 s, and usually later ([#167](https://github.com/yuriy-mikityuk/remind-eeg/issues/167)). Epochs are 30 s long and the gate needs 60 s of stable REM confidence before it opens. `EpochBuilder` and the pilot commands accept a shorter `--stride-seconds`, but the pilot runners pass the epoch length (30 s) to the gate rather than the stride, so with a 10 s stride the stable window and the cooldown would run three times too fast. The gate has to be fed the stride first; until then keep the default 30 s.

## Does the eye-movement proxy use AF7 − AF8?

Yes, but it does not work yet ([#167](https://github.com/yuriy-mikityuk/remind-eeg/issues/167), [#116](https://github.com/yuriy-mikityuk/remind-eeg/issues/116)). It takes the mean absolute difference of successive raw AF7 − AF8 samples at 256 Hz, which mostly measures high frequencies (muscle and a 64 Hz line from the optics), while eye movements are slow. Its score is 1.0 in every epoch, so it carries no information. The planned fix is a low-pass of about 5 Hz before the difference and thresholds fitted on a REM night.

## Why did the EEG have extra samples and gaps?

BLE sometimes delivers the same packet twice, and the decoder used to turn every copy into four more samples per channel ([#160](https://github.com/yuriy-mikityuk/remind-eeg/issues/160)). On a 23 min run there were 43 repeats, and 888 of 90,011 EEG subpackets (1.0 %) were lost. Since 0.1.0 the decoder drops a subpacket that repeats one of the last 16 with the same TAG and marks lost ones as gaps without filling them in (#182). The same run showed the headband sampling at about 257.2 Hz by the host clock, not exactly 256.

## `discover` finds nothing on macOS

The terminal or app running Python may lack Bluetooth permission, and macOS then stops the process before Python logs anything. [`USAGE.md`](USAGE.md) has the workaround: a virtual environment launched through the framework `Python.app`.

## Why is there no sound off macOS?

Real playback goes through macOS `afplay`. The `system` backend falls back to `dry-run` when `afplay` is missing, so on Linux or Windows nothing is heard. The fallback is not hidden: `audio_playback.jsonl` records `backend_name` `dry-run` for every request.

## Where did `configs/` go?

The four YAML files under `configs/` were never loaded by any code and had drifted from it (for example a 0.7 REM threshold against the gate's 0.80/0.70, and 1.5 s fades against 0.25 s). They were deleted; the settings are the dataclass defaults listed in [`protocol.md`](protocol.md) and [`numbers.md`](numbers.md). The protocol was also described as `Konkoly-like`; it is a one-way, REM-timed cue protocol without eye-signal verification, and the papers it draws on are in [`references.md`](references.md).
