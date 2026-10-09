# Calibration run: muscle tension, paced breathing, H10 unclip

One ~23 minute recording with the Muse and a Polar H10 that checks three things the
meditation analysis leans on:

- whether the 55-95 Hz EMG indicator tracks muscle tension that actually moves the
  EEG metrics (LZC, 1/f slope), at the slight tension a meditation contrast would have;
- which of the three breathing-rate estimates (ACC spectral, ACC breath-by-breath,
  ECG-derived) is right, against a known pace;
- whether the H10 reconnects after the sensor is taken off the strap.

It is done with eyes closed, so the Mac leads it by voice (macOS `say`, Russian voice
Milena by default) and logs when every cue was actually spoken. The blocks files for
the analysis are cut from those logged times, not from the plan.

## Running it

In the setup app: connect the Muse, wait for good contact, put on the H10 strap, then
**Calibration run…** → **Start calibration**. The recording strip shows the current step
and the H10 status. When it is done, **Build calibration report** (also in Recent
recordings).

From a terminal (press Disconnect in the app first, the Muse takes one connection):

```bash
muse-tmr calibration-run [--address <muse>] [--polar-address <h10>] [--voice Milena] [--rate 170]
muse-tmr calibration-report data/recordings/session/<timestamp>_calibration
```

Ctrl-C stops the voice and the recording cleanly; the steps finished so far are kept.
`calibration-guide <recording>` is the voice part alone, which the app runs next to its
own recording.

### Second run: where the 64 Hz line comes from

The line sits at the optics sample rate (see `docs/meditation_metrics.md`). One terminal
session, about 33 min, the Muse and the H10 on throughout:

```bash
muse-tmr calibration-run --line-check --preset p21 --battery-pull
```

- `--line-check` first records 2 min each of `p1034`, `p21`, `p1034`, `p21` (four
  short recordings, the headband reconnects in between, eyes closed). Alternating
  keeps the line's own fading out of the comparison. It prints the line per segment
  and channel (fitted amplitude, height over 58-62/66-70 Hz) and a verdict, and writes
  `calibration/line_check.json`, which the calibration report shows on top. The four
  recordings sit next to the calibration one as `<name>_line1_p1034` and so on.
- `--preset p21` records the calibration itself without optics, so its numbers are
  checked on fresh data without the line.
- `--battery-pull` changes the H10 minute: unclip it, take the battery out for ~10 s
  (a coin opens the cover), put it back. The link really drops and the sensor clock
  restarts, which the first run did not test.

The line present in both `p1034` pieces and gone in `p21`: the optics put it there,
and meditation can be recorded on `p21` with heart rate and breathing from the H10.
The line on `p21` too: the source is elsewhere, look around the room. The check on
2026-10-09 gave the first answer, so the app records meditation and calibration on
`p21`, and `calibration-run` defaults to it.

## Protocol

Minutes from the first Muse frame:

| Time | Step |
| ---- | ---- |
| 0-1 | settle in, eyes closed |
| 1-3 | relaxed |
| 3-5 | jaw slightly tense, teeth lightly touching |
| 5-7 | relaxed |
| 7-9 | forehead slightly tense, brows a little up |
| 9-11 | relaxed |
| 11-12 | clench for 1 s every 3 s, on the voice |
| 12-13 | relaxed |
| 13-16 | paced breathing 6/min: in 4 s, out 6 s |
| 16-19 | paced breathing 12/min: in 2 s, out 3 s |
| 19-20 | eyes open, unclip the H10 from the strap |
| 20-23 | H10 back on, eyes closed, sit still |

The recording runs 20 s past the end so the last epoch is complete.

## What gets written

In the recording folder, under `calibration/`:

- `plan.json`: the protocol as run.
- `cues.jsonl`: every cue with its planned time and the time it was spoken
  (`elapsed_s`, seconds from the first Muse frame).
- `segments.json`: actual start and end of each step, paced cycle starts, stop reason.
- `blocks_jaw.json`, `blocks_forehead.json`, `blocks_clench.json`: one
  analyze-meditation blocks file per tension step, contrast tension - relaxed. Each
  tension step is compared with relaxed windows of its own length right before and
  after it, so linear drift cancels (same idea as the ABBA order in meditation plans).
- `blocks_breathing.json`: 6/min vs 12/min.
- `state.json`: the current step, for the app.

These are personal recordings: keep them out of git like the rest of `data/`.

## The report

`calibration-report` writes `data/reports/calibration/<name>/report.html` plus
`summary.json`, and a full meditation report per pair in subfolders. Epochs are 10 s and
the first 10 s of each step are skipped (tension starts right after the instruction).

- **Muscle tension**: per step, the 55-95 Hz and 30-45 Hz power change in dB on AF7/AF8
  and TP9/TP10, and the shift in all-channel LZC and the 1/f exponent (2-40 and 2-20 Hz),
  for all epochs and for clean ones (artifact flags can drop exactly the tense epochs).
  The jaw should show on TP9/TP10 (temporalis), the forehead on AF7/AF8 (frontalis).
  The question is whether 55-95 Hz rises clearly at the slight levels while LZC and the
  slope move; 30-45 Hz is the EMG that overlaps the EEG metrics, 55-95 Hz only its proxy.
- **55-95 Hz over the run**: per-epoch power with the tension steps shaded; the first
  minutes show how long the muscles take to settle.
- **Breathing against a known pace**: the three estimates and their error on the paced
  steps, skipping the first 10 s after the first cue.
- **Inhale vs exhale**: chest ACC and heart rate averaged over the paced cycles from the
  "inhale" cue. Oriented by the cues, ACC rises through the inhale, so its peak should
  sit at the exhale cue. The trough says little: after a quick passive exhale the chest
  rests until the next inhale (on the first run the peak came 0.3 s and 0.1 s after the
  exhale cue, while trough-to-peak was 0.76 and 0.64 of the cycle for a paced 0.4).
  Heart rate rises on the inhale, so the last column checks whether HR alone picks the
  same ACC direction; if it does, inhale and exhale can be told apart without cues. On
  the first run it did at 6/min (13.5 bpm swing) and not at 12/min (1.2 bpm, lagging
  by about half a cycle).
- **H10 unclip**: when skin contact was lost and came back, Bluetooth disconnects and
  reconnects, the longest ECG gap, and the ECG rate in the last minute. On the first
  run the ECG never stopped and the link stayed up; only the contact flag showed it,
  ~25 s after the cue, and the H10 kept sending RR made of noise. Those beats are now
  dropped (see `docs/polar_h10.md`).

## Limitations

- One run is one person on one day. It calibrates the indicator for this headband and
  this face, it does not validate it in general.
- Tension levels are self-produced and only roughly graded ("slight" vs 1 s clenches).
- Paced breathing is followed by ear; the first cycles and late reactions blur the
  peak timing a little.
- The voice is Russian; another `--voice` works, but the instructions stay Russian.
