# Meditation complexity metrics

A side track to the REM/TMR work: check on my own Muse data whether the
direction of the jhana vs breath-mindfulness result from Mago et al. 2025 shows
up when I compare two of my own practices. The code lives in
`muse_tmr.features.complexity_features` and
`muse_tmr.reports.meditation_analysis` and does not touch REM detection, the
gate, the scheduler, the arousal guard or audio.

Reference: Mago et al., "Meditative absorption shifts brain dynamics toward
criticality", arXiv:2511.20990. **Preprint, not peer reviewed.** They found,
for jhana vs mindfulness of breathing: higher Lempel-Ziv complexity, sample and
permutation entropy and Hjorth mobility, a flatter aperiodic 1/f slope, a lower
largest Lyapunov exponent, lower theta/alpha/beta and higher low-gamma DFA,
lower alpha and higher gamma power. 10 experienced practitioners, 32-channel
EEG, 10 s epochs, no correction across metrics.

## Protocol

1. Once, before the first session: run the artifact diagnostic so you know what
   your own EMG looks like on TP9/TP10:

   ```bash
   muse-tmr diagnose-blink-artifacts --source amused --address "$MUSE_ADDR"
   ```

   That report only has amplitude metrics. To see the EMG indicators
   themselves, also record a short jaw check and analyze it as two conditions:

   ```bash
   muse-tmr meditation-plan --conditions relaxed,clench --blocks 4 \
     --block-minutes 1 --settle-seconds 30 --seed 1 --output data/protocol/meditation/jaw_check.json
   # record ~5 min, relax / lightly clench the jaw per the printed schedule, then
   muse-tmr analyze-meditation data/recordings/session/<name> \
     --blocks data/protocol/meditation/jaw_check.json --trim-block-start 10
   ```

   `emg.condition_difference` in the summary should show a clear clench > relaxed
   difference in `emg_power_55_95`.

   The setup app can run steps 2-4 for you ("Meditation…" when the headband is
   connected): plan, block timer with a soft tone at each change, ratings after
   each block, and the analysis with a link to its report. See
   `docs/contact_setup_local_app.md`. The steps below are the same by hand.

2. Per session, generate a counterbalanced plan:

   ```bash
   muse-tmr meditation-plan --conditions focus,open --blocks 4 --block-minutes 8 \
     --settle-seconds 60 --seed 17
   ```

   The order is ABBA or BAAB (ABBABAAB or BAABABBA for 8 blocks), picked by the
   seed and stored in the file. Plain ABAB puts A half a block earlier on
   average, so slow drift (relaxing, drowsiness, electrodes settling) would land
   in the contrast; this order cancels linear drift within every four blocks, so
   the block count must be 4, 8 or 12 (6 would leave a third of a block's drift). Times
   are seconds from the first recorded frame, which is what the app's recording
   timer shows. Eyes closed in both conditions.

3. Start a `session` recording in the app (or `muse-tmr record --allow-short`),
   follow the printed block times, and after each block fill in `depth` and
   `sensory_fading` (0-10) in the blocks file. It is personal data: keep it under
   `data/protocol/` (gitignored), never commit it.

4. Analyze:

   ```bash
   muse-tmr analyze-meditation data/recordings/session/<name> --blocks <blocks.json>
   ```

   Writes `epochs.csv`, `blocks.csv`, `summary.json` and a readable `report.html`
   (primary result per block, EMG check, breathing/HRV, paper metrics, blocks,
   limitations) to `data/reports/meditation/<name>/`. 40 min of synthetic 4-channel data with the
   Lyapunov exponent on takes about 40 s on an M-series laptop; `--no-lyapunov`
   skips the slowest metric.

5. After at least 8 sessions, aggregate:

   ```bash
   muse-tmr aggregate-meditation data/reports/meditation/*/summary.json \
     --output data/reports/meditation/aggregate.json
   ```

   The inference unit is the session: one A - B difference of block means per
   session. Epochs are autocorrelated and would inflate significance. With fewer
   than 8 sessions it prints descriptives and a warning and reports no p-values or
   intervals. With 8 or more: two-sided sign-flip permutation test (exact up to
   16 sessions) and a bootstrap 95% CI.

**Primary metric, declared up front: the raw all-channel mean LZC contrast on
clean epochs.** Everything else, including the all-epochs variant and the
EMG-residualized contrasts, is labeled exploratory in the outputs.

## Epochs and blocks

- 10 s non-overlapping epochs from `EpochBuilder`; partial epochs are dropped.
- An epoch counts for a block only if it lies wholly inside it after trimming the
  first 30 s of the block (`--trim-block-start`). The settle period and anything
  outside blocks are ignored.
- Artifact flags (clipping, flatline, empty, nonfinite, low coverage) come from
  `eeg_features`, plus `eeg_missing_<ch>` / `eeg_short_<ch>` when one of the four
  channels is absent or shorter than 2 s, so a "clean" group mean never silently
  covers fewer channels. Flagged epochs are kept and marked; flagged channels get
  NaN and are left out of the group means. Every contrast is reported twice: `all` epochs
  and `clean` epochs.
- Channel groups: per channel, `all` (mean of the four), `frontal` (AF7, AF8),
  `temporal` (TP9, TP10).

## Metrics

All parameters live in `ComplexityConfig` and are written into every
`summary.json`.

| Metric | Definition |
| ------ | ---------- |
| `lzc` | LZ76 (Kaspar-Schuster) on the median-binarized signal, normalized by n / log2(n). |
| `sample_entropy` | m = 2, r = 0.2 * std, Chebyshev distance. |
| `permutation_entropy` | Order 3, delay 1, normalized to [0, 1]. |
| `spectral_entropy` | Welch PSD (2 s segments) over 0.5-40 Hz, normalized. |
| `hjorth_mobility`, `hjorth_complexity` | Derivative as `np.diff`, per-sample units. |
| `aperiodic_exponent_2_20`, `_2_40` | Log-log line fit of the Welch PSD with iterative peak exclusion (drop points more than 2 robust SDs above the line, refit). exponent = -slope; offsets reported too. |
| `lyapunov_max` | Rosenstein 1993, embedding dimension 7, delay 4 samples, Theiler window 64 samples, 32-step divergence curve, per second. **Experimental**: noisy and parameter-sensitive on 10 s windows. |
| `band_power_*`, `relative_power_*` | Welch PSD integrated over the existing `EEG_BANDS`. |
| `emg_power_30_45` (+ `_rel` to 1-45 Hz), `emg_power_55_95` | EMG indicators, see below. |
| `dfa_theta/alpha/beta/low_gamma/broadband` | Per block: band-pass, Hilbert amplitude envelope, DFA with 16 log-spaced windows from 1 s to 1/10 of the data. Built from contiguous clean runs of at least 20 s, each filtered on its own, then concatenated. Fit range and window count are in `blocks.csv`. |

Complexity metrics (LZC, entropies, Hjorth, Lyapunov) use a detrended,
zero-phase 0.5-40 Hz band-pass. Spectral and EMG metrics use the detrended
signal with a 50 Hz notch. Power metrics are contrasted, correlated and
residualized on log10.

## EMG check

Lower alpha, higher gamma, a flatter 1/f slope and higher entropy are also what
scalp EMG produces, and TP9/TP10 sit over the temporalis. So `summary.json`
always carries an `emg` section:

- `indicator`: `emg_power_55_95` (above 50 Hz mains, below its 100 Hz harmonic)
  when that band is at least 3 dB above the 110-125 Hz floor, otherwise
  `emg_power_30_45`, which overlaps EEG gamma and is a weaker check.
- `condition_difference`: A - B of the log10 indicator. Beyond 0.1 log10 units
  (about 26%) in either variant, `emg_confounded` is true.
- `correlations`: Spearman rho across epochs between the indicator and each
  metric. No p-values, epochs are autocorrelated.
- `residualized_contrasts`: each metric's A - B after regressing it on the log10
  indicator within the session (OLS on epochs). A contrast that disappears after
  residualizing is probably muscle.
- `group_difference_db`: the same A - B in dB for all channels, AF7/AF8
  (forehead, frontalis) and TP9/TP10 (jaw, temporalis). The report shows it
  next to the ratio.
- Compare `aperiodic_exponent_2_20` with `_2_40`: flattening only in 2-40 Hz
  points to EMG.

**Does Muse pass 55-95 Hz?** Checked on a 13 min Muse S Athena session
(`p1034`, amused decoder): the EEG stream runs at about 254 samples/s, so
Nyquist is 128 Hz. Above 60 Hz the spectrum is not a flat noise floor: it falls
with a log-log slope of about -4 down to 95 Hz, the 100 Hz mains harmonic
stands out above its neighbours, and 55-95 Hz sits about 23 dB above 110-125 Hz.
So the band carries signal and 55-95 Hz is the default indicator. That only shows
the band is not empty, not that it tracks the 20-40 Hz part of the EMG that actually
moves the metrics. `calibration-run` (see `docs/calibration_run.md`) checks that,
graded: slight jaw tension, slight forehead tension and clench pulses, each against
the relaxed minutes around it, with the dB change per channel group next to the LZC
and 1/f shift.

**The 64 Hz line.** The first calibration run showed most of that 23 dB was one
line at exactly fs/4 = 64 Hz (in sample terms), 40-45 dB above its neighbours on
every channel. It fades smoothly through a session (AF7 about 33 to 21 dB over
23 min) and does not react to muscles, so with it in the band the indicator fell
for 20 minutes and barely moved with clenching (+0.7 dB on AF). It is in the
earlier 13 min session too, and it is why that session's "EMG" seemed to settle
only by minute 8. `emg_power_55_95` and `emg_high_band_over_floor_db` now bridge
64 ± 1.5 Hz with the neighbouring bins (`emg_exclude_hz`); ±1 Hz already removes
it. Without the line 55-95 Hz is about 13 dB above 110-125 Hz at rest, clenching
raises it 8-9 dB, slight forehead tension 1.6 dB on AF7/AF8 and slight jaw tension
1.0 dB on TP9/TP10, while LZC moves 0.01-0.05 and the 2-40 Hz exponent flattens by
roughly 0.1 per dB. Summaries from before this change (`schema_version` 1 and 2)
carry the old indicator.

## Polar H10 breathing and HRV

When the recording was made with `muse-tmr record --with-polar`, `analyze-meditation`
reads its `polar/` folder (skip it with `--no-polar`). For each block's analysed window
(block start + trim to block end, same wall-clock base as Muse) `blocks.csv` gets
`cardio_*` columns: breathing rate from chest ACC (spectral and breath-by-breath), EDR,
mean HR, RMSSD, SDNN, RSA around the measured breathing rate, LF/HF, `hf_band_valid`,
RR correction and ECG match percentages, `acc_posture_change_pct` and `resp_reliable`.
They are contrasted A - B with group `chest` (exploratory), so `aggregate-meditation`
picks them up across sessions.

Breathing from chest ACC is only trusted when the chest was still (no 10 s window with a
slow shift above 150 mG in more than 10 % of the block) and the spectral and
breath-by-breath rates agree within 2/min. Untrusted blocks stay in `blocks.csv` but are
left out of the breathing contrasts, and `summary.json` lists them under
`cardio.breathing_unreliable_blocks`. On the first live H10 session both halves failed
this check (moving around, disagreeing estimates), which is exactly what it is for.

There are three breathing-rate estimates and nothing yet says which one to trust: the
ACC spectral peak, the ACC breath-by-breath median, and EDR from R-amplitude. On the
first live session they gave 8.6, 8.2 and 3.8/min for the same block, and EDR stayed at
3.7-3.8/min in both halves, close to the 0.05 Hz lower band edge (possibly slow
R-amplitude drift rather than breathing). So `cardio.breathing_methods` keeps the A - B
of each method, and the report shows all three per block with their spread.
`cardio.breathing_difference_bpm` is the median of the three method differences, and
`breathing_methods_disagree` is set when they are more than 1/min apart. Summaries with
`schema_version` 1 still hold the ACC spectral difference alone in that field; the
contrasts that `aggregate-meditation` reads are the same in both versions.

Breath-by-breath counting ignores humps under 0.5 std of the breathing component.
At a paced 6/min the chest rests after a quick exhale and small humps there were
counted as breaths (9.2/min) at the old 0.3 std; real breaths start around 0.8 std.

`cardio.breathing_confounded` is set when that median difference is above 1 breath/min:
slower breathing was one of the paper's findings for jhana, and it can also shift EEG
and HRV, so treat it as a confound for the EEG contrasts.

## Limitations

- n = 1 practitioner. 4 channels, reference at Fpz, temporal channels over the
  temporalis.
- Criticality markers are still debated, and the reference paper is a preprint.
- MMN (BLE timestamp jitter is tens to hundreds of ms, no Fz/Cz) and neuronal
  avalanches (4 channels) are not possible on this setup, and the jhana
  manipulation itself is not reproduced: this compares two of my own practices.
- No correction across the exploratory metrics. Only the primary metric is meant
  for a yes/no reading, and only after enough sessions.
