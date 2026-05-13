# Validation

Validation should separate protocol fidelity from behavioral effects.

Technical metrics:

- recording duration and modality coverage
- packet loss and reconnect downtime
- replay determinism
- feature extraction coverage
- REM gate stability
- cue scheduler eligibility decisions
- arousal guard blocks and stops

Behavioral metrics:

- dream report completion
- cue incorporation reports
- morning retest outcomes
- cued-vs-uncued comparison

Morning dream reports should preserve raw self-report text and structured yes/no fields
separately from later analysis. Puzzle incorporation should be counted only when the
report links dream content to a puzzle ID from the generated night session.

Morning retest results should cover every generated session puzzle. Solved/unsolved,
duration, confidence, and stored cue condition are the minimum fields needed before
cued-vs-uncued analysis.

Cued-vs-uncued analysis should keep raw report text out of summary metrics, preserve
per-puzzle rows for auditability, and report cue timing from scheduler logs when
available. Treat solve-rate and incorporation-rate deltas as descriptive until repeated
sessions provide enough samples per condition.

All reports must include limitations, especially small sample sizes and the difference between consumer EEG and laboratory PSG scoring.
