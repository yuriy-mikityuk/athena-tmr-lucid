# SDK And Private Data Policy

Official Muse SDK support, if added, must remain optional and local-only.

SDK must be downloaded separately and placed locally; do not commit.
The repository may contain adapter interfaces and stubs only; runtime SDK loading
must fail clearly until an integration can be implemented without committing
proprietary files.

Do not commit:

- official Muse SDK binaries, headers, frameworks, archives, installers, or copied docs
- closed-source vendor code
- keys, tokens, `.env`, certificates, or private credentials
- private overnight recordings
- personal sleep reports, dream reports, calibration files, or device identifiers
- private cue audio

Allowed:

- open-source code
- adapter interfaces and stubs
- synthetic fixtures
- explicitly reviewed small public test fixtures

Run the guardrail script before publishing SDK-adjacent or data-adjacent changes:

```bash
python scripts/check_forbidden_files.py
```

The guardrail checks tracked and unignored publishable files for SDK paths, vendor
binaries, SDK archives/installers, secrets, recordings, reports, and private audio.
Local SDK directories such as `sdk/`, `vendor/muse_sdk/`, `vendor/muse-sdk/`, and
`vendor/MuseSDK/` are ignored by git so developers can experiment locally without
making those files publishable.
