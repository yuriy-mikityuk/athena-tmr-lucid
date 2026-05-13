# Architecture

The project keeps the existing amused-py BLE implementation as the low-level Muse S Athena data source and adds a separate `muse_tmr` layer for REM-TMR/TLR workflows.

## Layers

1. Source adapters: convert live or external streams into common Muse frames.
2. Data layer: recording, metadata sidecars, and offline replay.
3. Feature layer: sleep epochs and EEG/IMU/PPG/HR features.
4. REM layer: heuristic and personal REM predictions.
5. Gate and safety layer: stable REM checks, motion/arousal checks, cooldowns, and emergency stop.
6. Protocol layer: puzzle assignment, TLR cues, TMR scheduler, and session state.
7. Report layer: dream report, puzzle retest, and cued-vs-uncued analysis.

The M0 scaffold intentionally avoids moving the existing top-level `muse_*.py` modules. Later issues can introduce adapters one component at a time.

## M1 Source And Recording Flow

`BaseMuseSource` defines the source contract: discover devices, connect, stream `MuseFrame` objects, and stop. `AmusedSource` adapts the existing `MuseStreamClient` callback model into that contract.

`OpenMuseLslSource` is the optional M7 source. OpenMuse runs outside this process and
publishes Lab Streaming Layer streams; the adapter resolves stream names such as
`Muse_EEG` and `Muse_ACCGYRO`, converts pulled samples into `MuseFrame` objects, and
does not make OpenMuse or LSL packages mandatory for normal installation.

`MuseSdkSourceStub` reserves the future official SDK source interface without importing
or bundling any proprietary SDK files. Runtime SDK operations fail with a policy error
until a local-only integration is explicitly implemented.

`OvernightRecorder` consumes any `BaseMuseSource`, writes `raw_amused.bin`, `metadata.json`, `events.jsonl`, and `summary.json`, and uses `RecordingWatchdog` to detect no-data timeouts and modality dropouts.
