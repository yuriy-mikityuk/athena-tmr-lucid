# Changelog

Versions follow `muse_tmr.__version__`; the app shows the running version and build at the bottom of the page.

## 0.3.0 (2026-10-19)

### Local app

- The Recordings tab lists 30 recordings at a time with Show older, orders them by the start in the folder name (also behind a prefix like `smoke_muse_h10_`), and no longer redraws every 5 s when nothing changed (#204).
- After a meditation each block's ratings sit on a line of their own, and a disconnected headband shows a hint instead of four "missing" channel rows (#206).
- A setup form scrolls into view when it opens, and its voice language select looks like the other fields (#208).
- When the app stops answering (quit, crashed or restarting), the page says it is out of date and that a running recording keeps going, and dims what it last saw, instead of showing a frozen "Connected" (#212, #220).
- An app update no longer reloads the page over Morning answers that are not saved yet; it waits for the save and says so at the bottom of the page (#214).
- The page and the meditation guide follow the system's dark mode, like the reports (#213).
- After a meditation or a calibration run the main button is that recording's own analysis; the REM report is no longer offered there and stays on the Recordings tab (#217).

### Reports

- The meditation and calibration reports give the time they were made in local time, like the REM report, instead of UTC (#210).
- The Athena TMR mark at the top of a report takes its colours from the theme, so it stays clear in dark mode (#213).

### Development and docs

- CI's page check also cuts the page off the network, fakes an app update and freezes the page, so the not-answering banner and the hold on updates are tried in a real browser (#212, #214, #220).
- The local app runbook describes the hold on updates and the not-answering banner (#222).

## 0.2.0 (2026-10-19)

### Local app

- The app is called Athena TMR and shares the meditation guide's look. The Record tab puts the headband on the left and the five recording modes on the right, each saying what it records; a running recording shows its progress, battery, EEG rate and lost subpackets; the Recordings tab lists every recording with its reports and the same EEG numbers. The page, the guide and the macOS launcher share one icon (#185).
- A Morning tab for the day after a puzzle night: the dream report and a blind, timed retest, saved through the same code as `record-dream-report` and `record-puzzle-retest` and never showing which puzzles were cued (#186).
- During a recording the browser tab shows its time, `muse-tmr app --help` and the runbooks use the new name, and reports opened from the app get its icon (#200).

### Reports

- The REM, meditation and calibration reports share the app's look, with a dark mode and still no external loads, and open with "Athena TMR" and their kind. The REM report's title reads "REM report · Sat 17 Oct 2026, 16:22" in local time, like its chart, and it is a whole HTML document with a UTF-8 charset rather than a fragment (#196).

### Development and docs

- CI opens the app's page in headless Chrome, goes through its tabs and fails on any page error (#194).
- The README shows the Record, Recordings and Morning tabs (#198).

## 0.1.0 (2026-10-19)

The first tagged version. It covers what `main` could do on that date.

### Recording

- Overnight and short recordings from the Muse S Athena over BLE through the forked amused-py layer: EEG, IMU, PPG optics, heart rate and battery, with reconnects, a `progress.json` heartbeat and a `summary.json` at the end.
- Every BLE notification is kept as received in `raw_amused.bin`, so replay runs the same decoder as the live stream, from 0x to 20x speed.
- The decoder drops repeated subpackets and marks lost ones as gaps in `EEGSample` and `PPGSample` without filling them in (#182).
- OpenMuse (LSL) and BrainFlow sources produce the same `MuseFrame`. A Polar H10 chest strap can record ECG, RR and chest motion alongside, in its own process.

### Local app

- Live contact for TP9, AF7, AF8 and TP10 with a headband view and a check mark when all four are good (#187), headset scan, battery and decoder diagnostics.
- Session (1 h, p1034), night (8 h, p21), guided meditation, meditation series and calibration recordings, each run as its own `muse-tmr record` process under `caffeinate`.
- A start waits until all four channels have been good for 5 s, and the server refuses a start before that (#189).
- Reports are built from the page, recent recordings stay listed, and the app updates itself from `main` when idle. A macOS launcher installs it on the Desktop.

### REM detection and cueing

- 30-second epochs with coverage and quality flags; EEG band powers and ratios, an eye-movement proxy, IMU motion and arousal proxies, PPG heart rate and HRV proxies.
- A heuristic REM detector with reason codes, and a personal logistic regression classifier trained on annotated epochs and saved as versioned JSON.
- A stable REM gate with preset-dependent thresholds (0.90/0.85 on p21), an arousal guard, and a cue scheduler that runs a TLR block first and then only the cued puzzle cues, played under calibrated volume caps with fades and an emergency stop.
- `scripts/validate_rem_detection.py` scores the detector and the gate against YASA or GSSC staging.

### Protocol

- Puzzle catalogs, timed attempts, seeded cued and uncued assignment, cue association checks and TLR cue training.
- Morning dream reports, blind puzzle retests and the cued-vs-uncued analysis.
- Five staged pilots, each with a runbook and a validator.

### Meditation side track

- A/B sessions in ABBA or BAAB order with a tone and a voice cue in English or Russian at each change, and stability, sensory fading and drowsiness ratings per block.
- An HTML report with complexity metrics, an EMG check and, with the H10, breathing and HRV; series aggregation with p-values from 8 sessions on; a 23-minute voice-guided calibration run.

### Packaging and docs

- Installs as `athena-tmr-lucid` with every `muse_tmr` subpackage; CI builds the wheel and checks it (#188).
- A first-recording quick start in the README, runnable feature examples in `docs/USAGE.md`, and a short agent rules page (#190).
