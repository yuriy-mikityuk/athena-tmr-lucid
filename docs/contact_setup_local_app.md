# M10 Local App Contact Setup Runbook

Use this local web app before overnight Pilot sessions to confirm Muse connection,
EEG contact quality, and the backend-enforced pre-session start gate. This is a
local-only tool served from your machine. It is not a cloud service and does not
upload recordings, contact data, device identifiers, or reports.

## Required Channels

V1 contact setup tracks these Muse EEG contact channels:

- `TP9`: left rear/temporal contact.
- `AF7`: left front contact.
- `AF8`: right front contact.
- `TP10`: right rear/temporal contact.

The setup gate requires all four channels to be `good` for the stability window
before a session start is allowed.

## Mock UI Smoke Test

This command requires no Muse, BLE access, or macOS Bluetooth permission:

```bash
cd /path/to/athena-tmr-lucid
.venv/bin/muse-tmr app --source mock --host 127.0.0.1 --port 8765 \
  --mock-scenario mixed_fair_good
```

Open:

```text
http://127.0.0.1:8765
```

Useful mock scenarios:

- `all_missing`
- `one_channel_poor`
- `mixed_fair_good`
- `all_good`
- `flapping_af7`
- `disconnect_after_good`
- `stale_data`

Stop the app with `Ctrl-C` in the terminal running the command.

## Live Muse UI Smoke Test

Prepare the headset before launching the live app:

- Close the mobile Muse app so it does not hold the Bluetooth connection.
- Keep the Mac near the headset.
- Put the headset on before contact testing.
- Move hair away from the forehead sensors and the temporal/rear contacts.
- If the headband was charging, unplug it and wait briefly before discovery.

Run:

```bash
cd /path/to/athena-tmr-lucid
export MUSE_ADDR="<MUSE_BLE_ADDRESS>"
.venv/bin/muse-tmr app --source amused --address "$MUSE_ADDR" \
  --host 127.0.0.1 --port 8765
```

If you do not know the address, discover first:

```bash
.venv/bin/muse-tmr discover --source amused
```

Then open:

```text
http://127.0.0.1:8765
```

The default bind address is `127.0.0.1`. Do not expose the app on the LAN unless
you intentionally pass an explicit host such as `--host 0.0.0.0`.

Stop the app with `Ctrl-C`.

## macOS Launcher Icon

To create a clickable launcher on your Desktop:

```bash
cd /path/to/athena-tmr-lucid
export MUSE_ADDR="<MUSE_BLE_ADDRESS>"
.venv/bin/python scripts/install_macos_launcher.py --address "$MUSE_ADDR"
```

This installs:

```text
~/Desktop/Muse TMR Setup.app
```

Double-clicking the app starts the local setup server through Terminal and opens
`http://127.0.0.1:8765` when the server is ready. If the server is already running,
the launcher just opens the browser UI. Stop the app with `Ctrl-C` in the Terminal
window.

Use `--force` to replace an existing launcher after changing the Muse address,
repo path, or port:

```bash
.venv/bin/python scripts/install_macos_launcher.py --address "$MUSE_ADDR" --force
```

## macOS Bluetooth Permission Troubleshooting

On macOS, CoreBluetooth can terminate or block BLE access when the launching app
does not have Bluetooth permission metadata. If live discovery or connection fails
before useful Python logs appear:

- Confirm the mobile Muse app is closed.
- Toggle the headset off/on and retry discovery.
- Check System Settings -> Privacy & Security -> Bluetooth for the terminal or
  Python launcher you are using.
- Prefer a Homebrew Python virtualenv launched through `Python.app` when direct
  terminal Python is blocked by TCC.

Example `Python.app` launch pattern:

```bash
cd /path/to/athena-tmr-lucid
export MUSE_ADDR="<MUSE_BLE_ADDRESS>"
open -W -n /opt/homebrew/Frameworks/Python.framework/Versions/3.12/Resources/Python.app \
  --args -m muse_tmr.cli.main app --source amused --address "$MUSE_ADDR" \
  --host 127.0.0.1 --port 8765
```

Adjust the Python.app path to your installed Homebrew Python version.

## Per-Channel Contact Troubleshooting

`TP9`:

- Check the left rear/temporal contact point.
- Move hair away from the left rear pad.
- Reseat the band so the rear-left segment rests flat.

`AF7`:

- Check the left forehead contact.
- Move hair and skin oils away from the sensor area.
- Slightly lower or level the front band if the contact remains poor.

`AF8`:

- Check the right forehead contact.
- Move hair away and confirm the right front pad is not lifted.
- Level the front band if only the right front contact is fair or poor.

`TP10`:

- Check the right rear/temporal contact point.
- Move hair away from the right rear pad.
- Reseat the band so the rear-right segment is not floating.

## Start Gate Behavior

Use the `Start when ready` button after the Muse is connected and the contact
visualization is updating.

Backend behavior:

- The UI arms the backend gate; it is not a frontend-only state.
- Any missing, poor, fair, stale, or disconnected required channel blocks start.
- All four required channels must be `good` for the default `5s` stability window.
- If any required channel drops before the window completes, the countdown resets.
- A direct session-start request is rejected while the contact gate is not ready.
- After a session is running, contact drops are warnings/log events only. They do
  not automatically stop the session.

## UI Smoke Checklist

- Discovery finds the Muse.
- Connect succeeds.
- Contact data updates live.
- The source badge clearly shows `MOCK` or `LIVE Muse`.
- The device card shows the headset name, address, source, connected duration,
  and last packet age when available.
- Poor, fair, and good visual states are visible.
- Fair/poor channels show their primary reason code in human-readable form.
- Each channel maps to the expected segment: `TP9`, `AF7`, `AF8`, `TP10`.
- Per-channel sparklines update for recent contact fill history.
- All-good contact shows the centered check mark.
- `Start when ready` arms the contact gate.
- The stability progress bar counts toward the required contact window and
  reports the channel that reset the countdown.
- Session start remains blocked until all contacts are good for the stability
  window.
- Once running, the session strip shows elapsed time, warning count, and stream
  rate.
- In-session contact drops appear in the contact warning log but do not stop the
  session.
- The diagnostics panel exposes notification rate, EEG rows/sec, EEG effective
  rate, decode errors, unknown TAG counts, and last packet age.
- Disconnect or stale contact resets readiness before session start.

## Live Diagnostics

The local app exposes live source diagnostics at:

```text
GET /api/muse/diagnostics
```

For the `amused` source, the payload includes packet/frame counts, decoder
TAG counts, unknown TAG counts, decode errors, telemetry/battery summaries,
cumulative sample rates, and rolling sample rates over the decoder window. Use
this when checking whether a short live smoke is seeing startup jitter or
steady-state EEG/PPG rates.

Run this checklist before Pilot 4 or Pilot 5 overnight sessions.
