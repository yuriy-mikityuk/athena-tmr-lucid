# Open-source sleep staging and REM detection tools, with emphasis on real-time use on few-channel frontal/wearable EEG (state of the art as of October 2026)

Scope note: these notes cover third-party tools, models, datasets and standards only. remind-eeg itself is covered by other researchers. All performance numbers are reported with dataset and source; "κ" = Cohen's kappa; "F1" = per-class F1 unless stated; "≈" marks values I derived or that the source gives only approximately. Figures quoted from vendor or trade-press material are labelled as such.

## Key Question 1: General-purpose open tools (YASA, U-Sleep/U-Time, SleepTransformer, DeepSleepNet/TinySleepNet, braindecode, Luna POPS, MNE pipelines, sleepecg, PPG/HR staging, Somnolyzer). Which work with 2–4 frontal channels at ~256 Hz without EOG, and which support online inference?

### Takeaway
Every mature general-purpose open stager (YASA, U-Sleep, Luna POPS, SleepTransformer, DeepSleepNet family) was trained on clinical PSG with central/occipital derivations and is designed for whole-night offline scoring; none ships an online/streaming mode, and the only EEG+EOG-free foundation-model benchmark found puts YASA's EEG-only REM F1 at ≈0.55 on MESA. When applied as-is to frontal headband EEG, YASA reaches κ≈0.40–0.45 (REM recall 0.62) on ZMax at home, whereas ensembles or retrained frontal-specific models (ezscore-f, DreamentoScorer, Salfi 2026 ensemble) reach κ 0.72–0.84 with REM F1/accuracy 0.83–0.94, so retraining on frontal data matters more than the choice of architecture.

### Cited Findings

#### YASA (Raphael Vallat)
- Repo https://github.com/raphaelvallat/yasa; BSD-3-Clause; Python; 590 GitHub stars; installable with `pip install --upgrade yasa`, `uv pip install yasa` or `conda install -c conda-forge yasa`; the README image links reference v0.6.5 — [YASA GitHub](https://github.com/raphaelvallat/yasa)
- Model: LightGBM gradient-boosting classifier (500 estimators, max depth 5, 90 leaves, 60% feature fraction) on hand-engineered time/frequency features that are smoothed and z-scored per night; trained on 3,163 full-night PSGs from seven NSRR datasets (CCSHS 414, CFS 586, CHAT 351, HomePAP 82, MESA 575, MrOS 565, SHHS 590), >31,000 h, almost 4 million 30-s epochs — [Vallat & Walker 2021, eLife](https://elifesciences.org/articles/70092)
- Required input: one central EEG channel (C4-M1, C3-M2 or C4-Fpz recommended); EOG (E1-M2) and EMG (chin) optional; data are automatically downsampled to 100 Hz; the docs say "Do NOT transform (e.g. z-score) or filter the signal before running"; features are smoothed with a 7.5-min centered triangular rolling average plus a 2-min past rolling average and then robust-z-scored; output is a hypnogram plus per-epoch class probabilities (`hyp.hypno`, `hyp.proba`); classifiers were trained only on full-night recordings, so naps need full inspection — [yasa.SleepStaging docs](https://yasa-sleep.org/generated/yasa.SleepStaging.html)
- Performance on 585 held-out NSRR nights: median accuracy 87.46%, median κ 0.819, median MCC 0.821; N1 F1 0.432, N3 F1 0.835, REM/N2/Wake median F1 ≥ 0.86 (exact REM value not given). On Dreem Open Datasets vs 5-scorer consensus: DOD-H accuracy 86.6 ± 6.2, κ 0.801, REM F1 92.6 ± 9.7; DOD-O accuracy 84.30 ± 7.85, κ 0.765, REM F1 88.87 ± 10.79 — [Vallat & Walker 2021](https://elifesciences.org/articles/70092)
- Ablation (testing set 1): single central EEG only → median accuracy 85.12%, κ 0.782; EEG + EOG → 86.92%, κ 0.809; adding EMG gave a "negligible benefit". EEG-only REM F1 is not reported — [Vallat & Walker 2021](https://elifesciences.org/articles/70092)
- Speed: a full night at 100 Hz is "processed in less than 5 s" on a consumer laptop (≈10–20 s including loading, vs ≈10–20 min for Stephansen et al. 2018) — [Vallat & Walker 2021](https://elifesciences.org/articles/70092)
- Real-time: the maintainer states YASA "was only designed for offline uses, and therefore will not work for real-time scoring"; the suggested workaround is to re-run YASA on the growing buffer after every completed 30-s epoch — [YASA discussion #56](https://github.com/raphaelvallat/yasa/discussions/56)
- Frontal single-channel headband (ZMax F7-Fpz, at home, 100 participants, Wearanize+): YASA v0.6.5 κ = 0.400 over all subjects; in the 74 "OK" signal-quality recordings κ = 0.450, accuracy 60.0%, REM recall 0.62, N2 recall 0.64; left channel κ 0.450 vs right 0.350; U-Sleep on the full PSG montage of the same nights κ = 0.761 ± 0.092 — [Parry & Briganti 2026, medRxiv](https://www.medrxiv.org/content/10.64898/2026.06.01.26354591v1.full)
- EEG-only, no EOG (MESA, 350-subject subsample, 3 scalp EEG derivations): YASA zero-shot macro-F1 0.4720, accuracy 0.6687, REM F1 0.5531; fine-tuned BIOT 0.7237 / 0.8007 / 0.7301; LaBraM 0.6835 / 0.7737 / 0.6647; SleepFM-FS 0.6582 / 0.7757 / 0.7201. EOG was not evaluated at all; κ not reported — [Mehdi et al. 2026, arXiv 2609.22105](https://arxiv.org/html/2609.22105v1)
- A pure-R port of the YASA LightGBM model exists (mrpheus) — [mrpheus sleep-staging vignette](https://circadia-bio.r-universe.dev/mrpheus/doc/sleep-staging.html)

#### U-Sleep / U-Time (Perslev et al.)
- Repo https://github.com/perslev/U-Time; MIT; Python/TensorFlow (v2.8.0 for GPU); 319 stars, 524 commits; `ut` CLI (`ut extract` resamples to 128 Hz into HDF5; `ut train`; `ut predict`); the pre-trained U-Sleep model is accessed through the sleep.ai.ku.dk web service (Python bindings in a separate repo), and also via the commercial youSleep platform; the page gives no fine-tuning instructions and no real-time mode — [U-Time GitHub](https://github.com/perslev/U-Time)
- Paper: trained/evaluated on 19,924 PSG records from 15,660 participants across 16 clinical studies; "requires only a single EEG and a single EOG channel with arbitrary standard electrode placement"; fully convolutional 12-block encoder/decoder, ≈3.1 M parameters; weighted mean F1 0.79 across datasets (range 0.73–0.85); per-stage F1 Wake 0.91, N1 0.53, N2 0.86, N3 0.77, REM 0.90; DOD-H F1 0.79 ± 0.07 (= best human expert), DOD-O 0.76 ± 0.10 (best expert 0.74 ± 0.11); outputs stages at up to 128 Hz; whole recording scored in one forward pass in seconds on a laptop CPU; no EEG-only results reported — [Perslev et al. 2021, npj Digit Med](https://pmc.ncbi.nlm.nih.gov/articles/PMC8050216/)
- Web service: free for non-commercial use; upload anonymised EDF or HDF5, select channels and inference frequency — [Perslev et al. 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8050216/)
- On ZMax frontal headband data (69 recordings): U-Sleep v1.0 out of the box κ 57.3%; after 10-fold cross-validated fine-tuning with both EEG channels κ 71% — [Jafarzadeh Esfahani et al. 2023, bioRxiv](https://www.biorxiv.org/content/10.1101/2023.08.18.553744.full)

#### SleepTransformer, DeepSleepNet, TinySleepNet, DeepSleepNet-Lite
- SleepTransformer: repo https://github.com/pquochuy/SleepTransformer, 37 stars; README says CC-BY-NC-4.0 while the sidebar says MIT (inconsistent); MATLAB preprocessing + Python/TensorFlow 1.x; SHHS only; pretrained SHHS weights on Zenodo (record 7927282) — [SleepTransformer GitHub](https://github.com/pquochuy/SleepTransformer). Paper: SHHS accuracy 87.7%, κ 0.828, REM class F1 88.6 — [Phan et al. 2021, arXiv 2105.11043](https://arxiv.org/pdf/2105.11043)
- DeepSleepNet: https://github.com/akaraspt/deepsleepnet, 495 stars, Apache-2.0 but README says "For academic and non-commercial use only"; TensorFlow 1.15; Sleep-EDF (Fpz-Cz, Pz-Oz) and MASS (permission required); no pretrained weights (train 20 folds) — [DeepSleepNet GitHub](https://github.com/akaraspt/deepsleepnet)
- TinySleepNet: https://github.com/akaraspt/tinysleepnet, 179 stars, Apache-2.0 + same non-commercial note; Python 3.6/TensorFlow 1.13.1; CNN+RNN on single-channel raw EEG; Sleep-EDF only; no pretrained weights — [TinySleepNet GitHub](https://github.com/akaraspt/tinysleepnet); 1.3 M parameters per a 2026 comparison — [NanoSleep, arXiv 2608.18571](https://arxiv.org/pdf/2608.18571)
- DeepSleepNet-Lite (90-s input): Sleep-EDF-2013 accuracy 84.0%, macro-F1 78.0, κ 0.78; Sleep-EDF-2018 80.3 / 75.2 / 0.73 — [deepsleepnet-lite README](https://github.com/biomedical-signal-processing/deepsleepnet-lite/blob/main/README.md)

#### braindecode
- `SleepStagerChambon2018` is an architecture only: "no pretrained weights are distributed here. Instantiate the model and train it on your own data"; it takes `n_chans`, `sfreq`, `input_window_seconds` — [braindecode SleepStagerChambon2018 docs](https://braindecode.org/stable/generated/braindecode.models.SleepStagerChambon2018.html)
- braindecode re-hosts `SleepFMStager`, pretrained weights from SleepFM (Thapa et al., Nature Medicine 2026); input modalities BAS (brain activity), RESP, EKG, EMG at 128 Hz; one prediction per 5-s patch; 5 classes; license CC BY-NC 4.0 (not braindecode's BSD-3); no performance given on the card — [HF braindecode/SleepFMStager](https://huggingface.co/braindecode/SleepFMStager)
- SleepFM code: https://github.com/zou-group/sleepfm-clinical, CC BY-NC 4.0, 736 stars, pretrained on "over 585,000 hours of PSG recordings from approximately 65,000 participants"; staging mean F1 0.70–0.78 described as competitive with U-Sleep and YASA; three checkpoints listed; EEG-only operation not stated — [sleepfm-clinical GitHub](https://github.com/zou-group/sleepfm-clinical)

#### Luna / POPS (Purcell lab)
- Luna core engine: https://github.com/remnrem/luna-base, GPL-3.0, C/C++, 34 stars, 1,283 commits; command-line and embeddable tool for EDF/EDF+ polysomnography; Python interface `lunapi` (github.com/remnrem/luna-api); real-time not mentioned — [luna-base GitHub](https://github.com/remnrem/luna-base)
- POPS: "Luna's automated sleep staging system"; in prediction mode it computes features and applies a pre-trained model; the only distributed model is the single-EEG `s2` model trained on ~3,500 NSRR individuals using both C3-M2 and C4-M1 (treated as interchangeable); multiple channels are combined as the confidence-weighted mean of posteriors; Lunascope instead picks the most confident channel per epoch — [Luna POPS reference](https://zzz.bwh.harvard.edu/luna/ref/pops) and [SOAP/POPS vignette](https://zzz.bwh.harvard.edu/luna/vignettes/soap-pops) (both pages returned HTTP 503/404 during this research; statements are from search-engine extracts of those pages)

#### sleepecg (ECG/HR-based)
- https://github.com/cbrnr/sleepecg, BSD-3-Clause, 142 stars, `pip install sleepecg` (Python ≥ 3.9; `[full]` extra), JOSS 2023; ECG only; downloads/reads NSRR (MESA, SHHS) and PhysioNet data — [sleepecg GitHub](https://github.com/cbrnr/sleepecg); [JOSS paper page](https://joss.theoj.org/papers/10.21105/joss.05411)
- Pan & Tompkins heartbeat detector; 26 time-domain + 7 frequency-domain HRV features; bundled GRU classifiers (TensorFlow): wake/sleep accuracy 83% on 1,000 unseen test records; wake/REM/NREM 75% — [SleepECG JOSS PDF](https://www.theoj.org/joss-papers/joss.05411/10.21105.joss.05411.pdf)
- Last push April 2026 per a package index — [ecosyste.ms summary](https://summary.ecosyste.ms/projects/357126)

#### HR / PPG staging models (non-EEG)
- Sridhar et al. 2020: instantaneous heart rate from ECG R-peaks resampled to 2 Hz, CNN + dilated convolutions, receptive field 6–90 min, whole night padded to 10 h; trained on SHHS+MESA; SHHS held-out (800 nights) 4-class accuracy 77%, κ 0.66; CinC (993 nights) 72%, κ 0.55; REM recall/precision 0.81/0.76 (SHHS) and 0.76/0.66 (CinC) (≈F1 0.78 and 0.71, my calculation); authors state it "cannot be used for real-time sleep stage detection" and that releasing code "is not feasible" — [Sridhar et al. 2020, npj Digit Med](https://pmc.ncbi.nlm.nih.gov/articles/PMC7441407/)
- SleepPPG-Net: raw PPG resampled to ≈34 Hz, ResConv encoder + temporal convolutional network over a 10-h night; MESA-test median κ 0.75, accuracy 84%; CFS external κ 0.67 → 0.74 with transfer learning; no code URL or real-time claim — [Kotzen et al. 2022, arXiv 2202.05735](https://ar5iv.arxiv.org/html/2202.05735)
- Wrist PPG+accelerometer deep learning (Gillard et al. 2024): 4-stage accuracy 0.79, κ 0.66, vs expert inter-scorer accuracy 0.80–0.85, κ 0.70–0.75 — cited in [search summary of research.google listing](https://research.google/pubs/sleep-staging-classification-from-wearable-signals-using-deep-learning/)

#### Comparison table (general + wearable-specific tools; details and sources in the sections above and in KQ2)

| Tool | URL | License | Lang | Activity | Input | Model | Training data | Reported performance | Online/real-time | Validated on forehead EEG | pip |
|---|---|---|---|---|---|---|---|---|---|---|---|
| YASA | github.com/raphaelvallat/yasa | BSD-3 | Python | 590★, v0.6.5 | 1 central EEG (100 Hz), optional EOG/EMG | LightGBM | 3,163 NSRR nights | NSRR test κ 0.819; EEG-only κ 0.782; DOD-H REM F1 92.6 | No (offline by design) | Yes, poorly: ZMax κ 0.40–0.45, REM recall 0.62 | yes |
| U-Sleep | github.com/perslev/U-Time; sleep.ai.ku.dk | MIT (code); web free non-commercial | Python/TF | 319★ | 1 EEG + 1 EOG, 128 Hz | FCN U-Net | 15,660 participants | mean F1 0.79; REM F1 0.90 | No | ZMax κ 0.573 OOTB → 0.71 fine-tuned | no (web API) |
| SleepTransformer | github.com/pquochuy/SleepTransformer | CC-BY-NC / MIT (inconsistent) | MATLAB+TF1 | 37★ | 1 EEG | Transformer | SHHS | SHHS acc 87.7%, κ 0.828, REM F1 88.6 | No | Only inside Salfi 2026 ensemble | no |
| DeepSleepNet / TinySleepNet | github.com/akaraspt/… | Apache-2.0 + non-commercial note | TF1 | 495★ / 179★ | 1 EEG | CNN+RNN | Sleep-EDF, MASS | DSN-Lite Sleep-EDF κ 0.78 | TinySleepNet used per-epoch by Dreamento | TinySleepNet retrained on 1 person's ZMax+PSG in Dreamento | no |
| braindecode SleepStagerChambon2018 | braindecode.org | BSD-3 | PyTorch | active | any n_chans | CNN | none shipped | n/a | n/a | no | yes |
| SleepFM / SleepFMStager | github.com/zou-group/sleepfm-clinical | CC BY-NC 4.0 | Python | 736★ | BAS+RESP+EKG+EMG, 128 Hz | contrastive foundation model | ≈65,000 participants | staging F1 0.70–0.78 | No | no | via braindecode |
| Luna POPS | zzz.bwh.harvard.edu/luna | GPL-3.0 | C/C++ (+lunapi) | 1,283 commits | 1 central EEG (s2) | pre-trained (type not confirmed) | ≈3,500 NSRR | not found | No | no | lunapi |
| sleepecg | github.com/cbrnr/sleepecg | BSD-3 | Python/C | 142★, Apr 2026 | ECG R-peaks | GRU on HRV features | NSRR | wake/sleep 83%; W/REM/NREM 75% | not stated | n/a (ECG) | yes |
| ezscore-f | github.com/coonwg1/ezscore | MIT | Python/TF 2.13 | 111 commits, changelog Jul 2026 | 2 forehead EEG (L/R), 64 Hz | CNN+Transformer+BiLSTM | 160 ZMax+PSG nights | κ 0.73 (RT) / 0.75 (offline); REM acc 91.3% / 89.4% | Yes (ez6rt µV model) | Yes (ZMax; CGX patch κ 0.65) | `uv pip install -e .` from clone |
| Dreamento / DreamentoScorer | github.com/dreamento/dreamento | MIT | Python | 152★ | ZMax F7-Fpz, F8-Fpz, 256 Hz | TinySleepNet (RT default); LightGBM (offline) | ZMax | DreamentoScorer κ 0.722, REM F1 83.0; at-home κ 0.35–0.41 | Yes, every 30 s ("not ideal yet") | Yes (ZMax) | no (clone) |
| Portiloop | github.com/Portiloop | not shown | Python + FPGA/Coral | 241 commits | 1 EEG via ADS1299 | CNN+RNN spindle detector | MODA | spindle precision/recall ≈71%, ≈300 ms | Yes (spindles, not stages) | n/a | no |

### Inferences
- No general open stager offers a streaming API; YASA's smoothing windows (7.5 min centered, 2 min past) and per-night normalization make it structurally non-causal, so a "re-run every epoch" approach would both lag and shift features at the start of the night.
- The EEG-only MESA benchmark and the ZMax home-recording study agree that PSG-trained classical models lose most of their REM skill without EOG/central channels (YASA REM F1 ≈0.55 EEG-only on MESA; REM recall 0.62 on ZMax), whereas models retrained on frontal data recover REM F1/accuracy ≥0.83.
- For a 2–4-channel frontal device at 256 Hz, the usable off-the-shelf candidates are ezscore-f (direct fit: 2 forehead channels, real-time model, MIT) and, with retraining, LightGBM-style feature classifiers like DreamentoScorer/YASA; U-Sleep needs an EOG channel and fine-tuning; braindecode provides only architectures.

### Gaps
- No published κ or accuracy for Luna POPS could be retrieved (Luna documentation servers returned 503/404 during research).
- Somnolyzer (closed) and pyPPG were not characterised; no open PPG-staging weights (SleepPPG-Net or otherwise) were located.
- YASA's EEG-only REM F1 on its own NSRR test set is not reported in the eLife paper.
- The MESA channel-reduction benchmark excludes U-Sleep and reports no κ.

## Key Question 2: Wearable-specific published code/models and validations (Dreem/DOD, ZMax/Dreamento, Elemind, Earable/FRENZ, iBand, Portiloop, Muse S, in-ear EEG, PPG/HRV wearables)

### Takeaway
The only open, validated, frontal-EEG-specific stagers are ezscore-f (JHU/APL + Donders, MIT, trained on 160 ZMax+PSG nights, real-time variant κ 0.71–0.73) and Dreamento's DreamentoScorer (LightGBM, κ 0.72 in-lab but 0.35–0.41 at home); Muse S has only a closed InteraXon algorithm (κ 0.76 overall, REM κ 0.85 in a 2025 lab validation) and no open staging code was found; Dreem, Elemind, Earable/FRENZ and iBand algorithms are closed, though Dreem released the DOD PSG datasets and benchmark code.

### Cited Findings

#### Dreem (now Beacon Biosignals) and the Dreem Open Datasets
- Dreem headband validation: 5 dry electrodes (O1, O2, FpZ, F7, F8) giving 7 derivations, 250 Hz, 0.4–35 Hz band-pass, 3-D accelerometer and red/infrared pulse oximeter; 25 participants analysed; staging algorithm = two LSTM layers over 79 features (incl. expert-detected patterns) using the previous 30 epochs; vs 5-scorer PSG consensus: accuracy 83.5 ± 6.4%, κ 74.8 ± 10.4%; REM F1 82.9 ± 12.3%, REM κ 79.0 ± 13.7%; N1 F1 46.5%; algorithm not public, trained on internal Dreem data — [Arnal et al. 2020, Sleep](https://pmc.ncbi.nlm.nih.gov/articles/PMC7751170/)
- DOD-H (25 healthy nights) and DOD-O (55 OSA patients; 56 h5 files, one without consensus) are multi-scored PSG datasets (5 scorers, AASM); SimpleSleepNet F1 89.9% on DOD-H vs 86.8% for humans, 88.3% vs 84.8% on DOD-O — [Guillot et al. 2019, arXiv 1911.03221](https://arxiv.org/pdf/1911.03221); data on Zenodo (https://zenodo.org/records/15900394), h5 files with `Hypnogram` (-1 not scored, 0 W, 1 N1, 2 N2, 3 N3, 4 REM) and `Signals`; benchmark code MIT, 102 stars — [dreem-learning-open GitHub](https://github.com/Dreem-Organization/dreem-learning-open)
- RobustSleepNet (transfer learning across montages, "works out-of-the-box on new sleep studies (even with a different PSG montage)"), MIT, 38 stars, pretrained models included; 8 datasets (DODO, DODH, MASS, Sleep-EDFx, MrOS, MESA, SHHS, CAP) — [RobustSleepNet GitHub](https://github.com/Dreem-Organization/RobustSleepNet)
- Note: DOD datasets are PSG, not headband recordings; the 25 Dreem+PSG nights from Arnal 2020 are said to be "openly accessible via a hosted link" — [Arnal et al. 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7751170/)

#### ZMax (Hypnodyne) and Dreamento
- ZMax Lite: two frontal EEG channels F7-Fpz and F8-Fpz at 256 Hz, tri-axial accelerometer, PPG; 135 nights with simultaneous PSG; proprietary ZLab autoscoring κ 59.61%; open DreamentoScorer (LightGBM on features from both channels plus three epochs before and after) κ 72.18%; per-stage F1 DreamentoScorer W 77.36 / N1 39.73 / N2 81.23 / SWS 82.28 / REM 83.01 vs ZLab REM 76.30; DreamentoScorer made early REM detections, REM-latency correlation with PSG r = 0.20 (ZLab r = 0.38); authors note frontal-only wearables make autoscoring harder and PSG-trained algorithms may not transfer without fine-tuning — [Jafarzadeh Esfahani et al. 2023, bioRxiv](https://www.biorxiv.org/content/10.1101/2023.08.18.553744.full)
- Dreamento software: https://github.com/dreamento/dreamento, MIT, 152 stars, Python GUI; real-time recording via Hypnodyne HDServer, real-time autoscoring "open to any algorithm" but "not ideal yet, still under development"; offline LightGBM model file `clf_eeg_lgb_0.4.0.joblib` trained on >130 recordings; visual/auditory/tactile stimulation; environment pins TensorFlow 1.13.1 / Python 3.6; not on PyPI — [Dreamento GitHub](https://github.com/dreamento/dreamento)
- Dreamento paper: real-time analysis (autoscoring, spectrogram, periodogram) updates after every 30-s epoch (7,680 samples at 256 Hz); the default real-time autoscorer is TinySleepNet "trained on a dataset collected from a citizen neuroscientist who measured his nocturnal sleep with simultaneous ZMax and PSG"; the toolbox is explicitly offered for TMR and lucid-dream studies — [Jafarzadeh Esfahani et al. 2022, arXiv 2207.03977](https://arxiv.org/abs/2207.03977v2)
- At-home performance (Wearanize+, 100 adults): 10% of ZMax recordings failed completely, 16% partly degraded; Dreamento κ 0.349 (all), 0.371 OK group, 0.084 FAIL group; YASA κ 0.400 / 0.450; REM recall Dreamento 0.44 vs YASA 0.62; Dreamento mislabelled 37% of N2 as N3 — [Parry & Briganti 2026, medRxiv](https://www.medrxiv.org/content/10.64898/2026.06.01.26354591v1.full)
- Ensemble on a customised single fronto-mastoid ZMax channel (35 home nights, 10 participants, 250 h): soft-voting YASA + U-Sleep + SleepTransformer + DeepResNet → accuracy 88.83 ± 2.84%, κ 0.841 ± 0.045, F1 REM 93.99%, N3 89.53%, N2 87.93%, Wake 86.37%, N1 53.20%; no code link — [Salfi et al. 2026, J Sleep Res](https://ricerca.univaq.it/handle/11697/279579)

#### ezscore-f (forehead-EEG-specific, open)
- Hybrid CNN + two transformer branches + bidirectional LSTM; input two forehead derivations (L/R) high-passed at 0.5 Hz and downsampled to 64 Hz; models view up to 50 min of context but can classify a single 30-s epoch; training data: Wearanize+ (96 recordings) + Donders2022 (64 recordings) = 160 ZMax recordings from 126 individuals with concurrent PSG; loss = 90% cross-entropy + 10% soft-κ — [Coon et al. 2025, bioRxiv](https://www.biorxiv.org/content/10.1101/2025.06.02.657451.full)
- Results: artifact-naive 5-class on all data 63.9%, κ 0.49 (REM per-stage accuracy 24.2%); real-time artifact-aware µV model 79.2% / κ 0.71 (6-class incl. artifact), 80.3% / κ 0.73 as 5-class; offline normalized model 82.3% / κ 0.75; per-stage accuracy real-time REM 91.3%, N2 82.7%, N3 82.7%, Wake 56.8%, N1 33.6%; offline REM 89.4%; cross-device on the JHU/APL "DCM" patch without fine-tuning 76.4 ± 0.2%, κ 0.65 ± 0.02 (2 nights); the µV model is "designed for real-time use, such as closed-loop sleep interventions" — [Coon et al. 2025](https://www.biorxiv.org/content/10.1101/2025.06.02.657451.full)
- Repo: https://github.com/coonwg1/ezscore, MIT (JHU/APL 2025), Python 3.9–3.11, 14 stars, 111 commits, changelog entries dated July 2026; models `ez6`, `ez6rt`, `ez6moe`; input is an MNE `Raw` in volts with channels `eegl`/`eegr`, resampled to 64 Hz; loaders for ZMax EDF pairs, DCM EDF and CGX PatchEEG (500 Hz); install by cloning and `uv pip install -e .` — [ezscore GitHub](https://github.com/coonwg1/ezscore)

#### Muse S (InteraXon)
- Muse-S: four dry EEG channels Fp1, Fp2, TP9, TP10 referenced to Fpz, 256 Hz, accelerometer 52 Hz; staged by InteraXon's "sleep staging v2" (previously validated against two RPSGTs in a 2023 conference paper); 47 of 56 adults analysed (9 excluded for poor signal, 16%); overall κ 0.76 (95% CI 0.75–0.76); per-stage κ Wake 0.84, N1 0.41, N2 0.75, N3 0.77, REM 0.85; REM sensitivity 91.5%, specificity 96.8%, accuracy 96.0%; REM over-estimated by 6.4 min; signal quality degraded after 14–20 nights of use; lab setting with technician fitting — [Sleep Advances 2025, zpaf089](https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/)
- Earlier conference validation in good sleepers and sleep-apnea patients (SLEEP 2024 abstract) — [SLEEP 2024 abstract 1119](https://www.citedrive.com/en/discovery/1119-validation-of-a-portable-sleep-electroencephalography-device-in-good-sleepers-and-people-with-sleep-apnea/)
- No GitHub project applying YASA or a custom stager to Muse overnight data was found in two searches; the only Muse-specific open code found is the `amused` BLE streaming library (7-channel EEG at 256 Hz, PPG, IMU, binary recording + replay) — [amused on PyPI](https://pypi.org/project/amused/)
- Vendor marketing for Muse S Athena separates independent staging accuracy from internal improvement figures — [Muse Athena sleep page](https://choosemuse.com/pages/athena-sleep) (vendor material)

#### Earable/FRENZ, Elemind, iBand, Aurora
- FRENZ brainband: trade press reports a Scientific Reports study (Oxford/Colorado) with "88% sleep-scoring precision" vs PSG, a later company release says 89%; no κ reported; closed — [Sleep Review](https://sleepreviewmag.com/sleep-diagnostics/consumer-sleep-tracking/wearable-sleep-trackers/wearable-brainband-uses-ai-audio-improve-sleep/) (trade press)
- Consumer lucid-dream devices (iBand, Neuroon Open, Aurora) detect REM via EEG and cue with audio/visual stimuli; a 2019 review notes their accuracy "hasn't been proven" and Aurora's developers say their "REM-detection algorithm is not yet perfect" — [Mota-Rolim et al. 2019, Frontiers in Neuroscience](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6517539/)
- OSSMM (May 2026): open-source 3-D-printed headband (<40 EUR parts) with two frontal electrodes, EOG, pulse, movement, vibration motor and Android app; offline 4-class ML staging on 15 nights of one participant: macro-F1 0.770, accuracy 0.776, κ 0.63 vs PSG; no repository link in the abstract — [Giordano et al. 2026, arXiv 2605.18588](https://arxiv.org/abs/2605.18588)

#### Portiloop (real-time spindle detection)
- Open-source closed-loop device; CNN+recurrent network implemented on FPGA/Coral; spindle detection precision and recall ≈71% vs MODA expert consensus; stimulation within ≈300 ms of spindle onset — [Valenchon et al. 2022, PLOS ONE](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9394839/)
- Software repo: Python; Google Coral Dev Board Mini + Portiloop board (ADS1299); pluggable Processor/Detector/Stimulator; records CSV and streams over LSL; examples are spindles and slow oscillations, no sleep staging or REM detection; license not shown — [portiloop-software GitHub](https://github.com/Portiloop/portiloop-software)

#### Forehead patches and in-ear EEG
- CGX forehead patch (Fp1, Fp2, AFz, 500 Hz, 19 subjects) with spectral HMM scoring: visually scored REM recognised as spectral REM 89%; spectral REM confirmed as visual REM 64%; REM identified from a ≈17–26 Hz band refined ±2 Hz around each subject's peak; κ not reported — [Onton et al. 2024, Frontiers in Sleep](https://www.frontiersin.org/journals/sleep/articles/10.3389/frsle.2024.1349537/full)
- Ambulatory forehead electrode set (EEG+EOG+EMG, 135 recordings, suspected OSA/bruxism) with CNN+RNN: 5-stage 79.7%, κ 0.729; 3-stage W/NREM/R 89.1%, κ 0.801 — [Leino et al. 2022, IEEE Access](https://oulurepo.oulu.fi/handle/10024/31913)
- Ear-EEG transfer learning (older adults, LightGBM): 70.1% → 73.7% after fine-tuning, κ 0.639 — [Hammour et al. 2024, IEEE JTEHM](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11100860/); NextSense earbuds pre-trained on 1,100 PSGs then fine-tuned on 8 recordings: 77.3%, κ 0.647 (preprint) — [Research Square](https://researchsquare.com/article/rs-3965548/v1); single-channel in-ear ExG 4-class 65.1% (vs Apple Watch reference) — [Lepold et al. 2025, arXiv 2509.07896](https://arxiv.org/html/2509.07896v2)

### Inferences
- The devices with the strongest independent REM numbers (Muse S REM κ 0.85; Dreem REM κ 0.79) rely on closed algorithms; the open frontal models (ezscore-f, DreamentoScorer, Salfi ensemble) approach them only on ZMax and only when trained/ensembled on frontal data.
- ezscore-f is the closest open analogue to a Muse-style 2-frontal-channel real-time stager and already defines a generic `RawArray` path for "custom devices", which suggests it could be run on Muse Fp1/Fp2 (TP9/TP10 would be unused) — this is untested in any source found.
- Home-recording signal dropout (10% FAIL + 16% WARN on ZMax) is a dominant error source that no stager fixes; artifact-aware classes (ezscore-f's 6th class) are the open precedent for handling it inside the model.

### Gaps
- No peer-reviewed or open validation of Elemind was found; FRENZ κ unknown (only press "precision").
- The 2023 InteraXon conference validation of Muse "sleep staging v2" was not retrieved; its training data and architecture are undisclosed.
- Dreamento's real-time TinySleepNet scorer has no published agreement figures; only the offline DreamentoScorer was validated.
- Per-stage F1 for ezscore-f exists only in a figure (values not in text); DCM cross-device result rests on 2 nights.

## Key Question 3: REM detection specifically — from frontal EEG alone, from HRV/PPG, from IMU stillness; REM-vs-non-REM accuracy on frontal-only consumer EEG; latency suitable for real-time cueing (30 s–3 min)

### Takeaway
On frontal-only consumer EEG, REM is the best-detected stage once models are trained on such data (REM F1 0.83–0.94 on ZMax, REM per-stage accuracy ≈89–91% for ezscore-f, 89% REM sensitivity for spectral forehead scoring), whereas PSG-trained models fall to REM recall ≈0.62 / F1 ≈0.55; HR/PPG models reach 4-class κ 0.66–0.75 with REM recall ≈0.76–0.81 but all use whole-night context and are explicitly not real-time; IMU-only staging is reported as not feasible beyond sleep/wake. Only ezscore-f (single-epoch capable, causal µV model) and Dreamento (per-30-s-epoch TinySleepNet) document ≤30-s update intervals for staging; DreamentoScorer's offline model needs 3 future epochs (≥90 s lag).

### Cited Findings
- Frontal channels carry eye-movement information "useful for REM and N1 detection", which is why wearables with frontal electrodes only still make autoscoring "more challenging" overall — [Jafarzadeh Esfahani et al. 2023](https://www.biorxiv.org/content/10.1101/2023.08.18.553744.full)
- Frontal spectral signature used for REM without EOG/EMG: power in a ≈17–26 Hz band (per-subject peak ±2 Hz); frontal theta was judged "not consistent enough"; 89% of visual REM recognised, 64% precision; HMM continuity means spectral REM is rarely visual Wake (4%) — [Onton et al. 2024](https://www.frontiersin.org/journals/sleep/articles/10.3389/frsle.2024.1349537/full)
- REM on ZMax frontal EEG: DreamentoScorer REM F1 83.01% vs proprietary ZLab 76.30%; early REM detections lowered REM-latency agreement (r = 0.20) — [Jafarzadeh Esfahani et al. 2023](https://www.biorxiv.org/content/10.1101/2023.08.18.553744.full); Salfi ensemble REM F1 93.99% (single fronto-mastoid channel, home) — [Salfi et al. 2026](https://ricerca.univaq.it/handle/11697/279579); ezscore-f REM per-stage accuracy 91.3% (real-time) / 89.4% (offline), but only 24.2% for the artifact-naive baseline — [Coon et al. 2025](https://www.biorxiv.org/content/10.1101/2025.06.02.657451.full); YASA at home on ZMax REM recall 0.62, Dreamento 0.44 — [Parry & Briganti 2026](https://www.medrxiv.org/content/10.64898/2026.06.01.26354591v1.full)
- Closed-algorithm reference on Muse S (Fp1/Fp2/TP9/TP10): REM κ 0.85, sensitivity 91.5%, specificity 96.8% — [Sleep Advances 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/)
- Binary REM-vs-rest from a 3-stage grouping with forehead EEG+EOG+EMG: W/NREM/R accuracy 89.1%, κ 0.801 — [Leino et al. 2022](https://oulurepo.oulu.fi/handle/10024/31913)
- HR/HRV: Sridhar et al. REM recall/precision 0.81/0.76 (SHHS) and 0.76/0.66 (CinC); receptive field 6–90 min; "cannot be used for real-time sleep stage detection" — [Sridhar et al. 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7441407/); SleepPPG-Net 4-class κ 0.75 using a 10-h context — [Kotzen et al. 2022](https://ar5iv.arxiv.org/html/2202.05735); sleepecg's bundled wake/REM/NREM GRU classifier 75% accuracy — [SleepECG JOSS](https://www.theoj.org/joss-papers/joss.05411/10.21105.joss.05411.pdf); ECG-only foundation-model baselines on MESA reach REM F1 only 0.14–0.32 — [Mehdi et al. 2026](https://arxiv.org/html/2609.22105v1)
- IMU: wrist accelerometer random forest sleep/wake F1 73.93% on 24 unseen participants; "sleep stage classification turned out to be difficult using only accelerometer data" — [Sundararajan et al. 2021](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7794504/)
- Latency precedents: Dreamento updates autoscoring, spectrogram and periodogram after every 30-s epoch and drops queued samples to keep synchrony — [Jafarzadeh Esfahani et al. 2022](https://arxiv.org/abs/2207.03977v2); DreamentoScorer's offline features use three epochs before and after the scored epoch — [Jafarzadeh Esfahani et al. 2023](https://www.biorxiv.org/content/10.1101/2023.08.18.553744.full); ezscore-f models "can classify from a single 30-second epoch" while viewing up to 50 min of past context — [Coon et al. 2025](https://www.biorxiv.org/content/10.1101/2025.06.02.657451.full); Portiloop spindle stimulation within ≈300 ms — [Valenchon et al. 2022](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9394839/); a 2018 smartphone pipeline infers a stage from a single 30-s epoch (Sleep-EDF 83.5%, 5-class, single channel) — [Koushik et al. 2018, arXiv 1811.10111](https://arxiv.org/abs/1811.10111); YASA's 7.5-min centered smoothing is non-causal — [yasa.SleepStaging docs](https://yasa-sleep.org/generated/yasa.SleepStaging.html)
- Streaming test-time adaptation (StableSleep, 2025) claims seconds-level latency on single-lead Sleep-EDF but code is withheld until acceptance — [arXiv 2509.02982](https://arxiv.org/pdf/2509.02982)

### Inferences
- A frontal-EEG REM detector's realistic ceiling with open methods is REM F1 ≈0.83–0.94 (ZMax, lab/home with good contact); a per-epoch causal detector should expect lower recall than the 50-min-context ezscore-f numbers.
- REM-latency errors (early REM calls before first N2) are a documented failure mode of frontal LightGBM scorers; a "stable gate" or sequence constraint is the kind of fix the ZMax authors proposed (reclassify pre-N2 REM as N1).
- HRV/PPG REM information is real (recall ≈0.8) but every validated model needs minutes-to-hours of context; a 2–3-min HR context is below the 6–90-min receptive fields used, so PPG is realistically a supporting feature, not a standalone REM trigger.

### Gaps
- No source reports REM-vs-non-REM binary metrics for a causal (no future epochs) frontal-only model with ≤3-min latency; all frontal numbers above are offline or use multi-minute past context.
- No IMU-only REM detection result was found; no study quantifies REM-period stillness as a classifier on headband IMU.
- No paper quantifies sawtooth-wave or eye-movement-deflection detection from Fp1/Fp2 as a standalone REM detector.

## Key Question 4: Personalization — does per-subject fine-tuning improve wearable staging, and is there open code?

### Takeaway
Evidence consistently shows per-subject or per-device fine-tuning helps, from +2 percentage points on Sleep-EDF (2018) to κ 0.57 → 0.71 for U-Sleep on ZMax and 70.1% → 73.7% for ear-EEG LightGBM, and self-supervised pretraining on unlabeled headband data reaches >80% accuracy with 5–10% of labels; open code for these personalization pipelines is scarce (U-Time training CLI, ezscore repo, and generic braindecode exist, but no turnkey "fine-tune on my nights" tool).

### Cited Findings
- Fine-tuning a general CNN on each person's first night raised accuracy by ≈2 percentage points on average, more for subjects below 80%; best results combined ≥20 nights of general data with subject-specific data; main drawback is the need for labeled data from every subject (Sleep-EDF, single EEG) — [Mikkelsen & de Vos 2018, arXiv 1801.02645](https://arxiv.org/pdf/1801.02645)
- Single-night personalization of SeqSleepNet with a KL-divergence regularizer: 79.6% accuracy, κ 0.706 on 75 subjects — [Phan et al. 2020, arXiv 2004.11349](https://ar5iv.org/html/2004.11349)
- Source-free unsupervised domain adaptation with pseudo-label fine-tuning removes the need for target labels (AAAI 2025) — [AAAI paper](https://ojs.aaai.org/index.php/AAAI/article/view/33592)
- LightSleepNet: personalized single-channel EEG staging for portable devices; notes that fine-tuning with labeled target-subject data "is impractical at home" — [arXiv 2401.13194](https://arxiv.org/pdf/2401.13194)
- U-Sleep on ZMax: κ 57.3% out of the box → 71% after 10-fold fine-tuning with both frontal channels — [Jafarzadeh Esfahani et al. 2023](https://www.biorxiv.org/content/10.1101/2023.08.18.553744.full)
- Ear-EEG (older adults, LightGBM): 70.1% → 73.7%, κ 0.639, significant gains in 10 of 13 participants — [Hammour et al. 2024](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11100860/)
- Fine-tuning vs training from scratch for single-channel wearable EEG: fine-tuning "can yield similar to superior performance… while requiring a smaller sample size"; κ 0.67 in an RBD group — [Frontiers in Physiology 2023](https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2023.1287342/pdf)
- Self-supervised learning on Ikon Sleep headband data (BOAS labelled + HOGAR unlabeled home recordings): up to +10% over supervised baselines; >80% accuracy with 5–10% of labels vs ≈2× as many labels for supervised; outperformed general EEG foundation models — [Estevan et al. 2025/2026, arXiv 2510.07960](https://arxiv.org/abs/2510.07960)
- Closest open training code: U-Time's `ut train` CLI (no fine-tune recipe) — [U-Time GitHub](https://github.com/perslev/U-Time); YASA's training repo `raphaelvallat/yasa_classifier` — [yasa.SleepStaging docs](https://yasa-sleep.org/generated/yasa.SleepStaging.html); ezscore models and tutorials — [ezscore GitHub](https://github.com/coonwg1/ezscore); BOAS code on GitLab ("boas" under Bitbrain Public: preprocessing, deep-learning staging, validation) — [GitLab topic listing](https://gitlab.com/explore/projects/topics/sleep-staging)

### Inferences
- The combination that the literature supports for a single-user home device is: pretrain or ensemble on frontal data (ZMax/BOAS), then fine-tune or calibrate with a few self-annotated nights, with the largest expected gains for users whose baseline agreement is low.
- Because ZMax (F7/F8-Fpz) and Ikon (AF7/AF8) montages are frontal at 256 Hz, their datasets are the natural pretraining corpora for any Fp1/Fp2 device; the ezscore-f DCM transfer (κ 0.65 without fine-tuning) is the only cross-device evidence found.

### Gaps
- No study fine-tunes on a consumer headband with PPG/IMU inputs or reports REM-specific gains from personalization.
- No open repository implementing few-shot/single-night adaptation for wearable EEG was located (Phan 2020 and AAAI 2025 code availability not confirmed).

## Key Question 5: Benchmarks and datasets a small project could validate against (incl. simultaneous consumer-headband + PSG)

### Takeaway
Openly downloadable headband+PSG pairs exist: BOAS (128 nights, Ikon Sleep AF7/AF8 at 256 Hz + Micromed PSG, 3-expert consensus, OpenNeuro ds005555) and the Dreem 2020 validation nights; ZMax+PSG data (Wearanize+, 130 adults) require a Radboud data-use agreement; classic PSG corpora (Sleep-EDFx, DOD-H/O, CAP) are open, while SHHS/MESA/MrOS/CFS need NSRR approval and MASS needs permission; no open Muse+PSG dataset was found.

### Cited Findings
- BOAS: 128 overnight recordings from healthy adults, each monitored simultaneously by clinical PSG and the Ikon Sleep headband (two frontal electrodes AF7 and AF8 at 256 Hz, reference/ground on mastoids); PSG channels F3, F4, C3, C4, O1, O2, EOG, EMG, PPG, breathing, airflow; AASM labels by three experts, consensus when ≥2 agree, fourth scorer resolves disagreements — [Estevan et al., arXiv 2510.07960](https://arxiv.org/pdf/2510.07960); Bitbrain lists it as 128 nights with a Micromed PSG, human-consensus plus AI labels for both systems, download on OpenNeuro ds005555 (license not stated on the page) — [Bitbrain EEG datasets](https://bitbrain.com/science/eeg-datasets)
- Wearanize+: 130 healthy adults (100 in the "PlugNPlay" subset) with home PSG (SOMNOscreen Plus) and ZMax (F7-Fpz, F8-Fpz, 256 Hz); hosted in the Radboud Data Repository under a signed Data Use Agreement for non-commercial academic use — [Parry & Briganti 2026](https://www.medrxiv.org/content/10.64898/2026.06.01.26354591v1.full); ezscore-f used 96 Wearanize+ and 64 Donders2022 recordings (160 ZMax+PSG nights total) — [Coon et al. 2025](https://www.biorxiv.org/content/10.1101/2025.06.02.657451.full)
- ZMax validation corpus: 135 ZMax+PSG nights from four datasets (>900 h) plus 512 ZMax-only MindIBD nights — [Jafarzadeh Esfahani et al. 2023](https://www.biorxiv.org/content/10.1101/2023.08.18.553744.full) (availability not stated)
- Dreem+PSG 25 nights (Arnal 2020) "openly accessible via a hosted link" — [Arnal et al. 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7751170/)
- DOD-H/DOD-O: PSG, 5 scorers, Zenodo https://zenodo.org/records/15900394, h5 format — [dreem-learning-open](https://github.com/Dreem-Organization/dreem-learning-open)
- Sleep-EDF Expanded (PhysioNet): 197 whole-night PSGs (153 Sleep Cassette, 44 Sleep Telemetry); EEG Fpz-Cz and Pz-Oz at 100 Hz, horizontal EOG, submental EMG; hypnograms in EDF+; Open Data Commons Attribution License v1.0 — [PhysioNet sleep-edfx](https://physionet.org/content/sleep-edfx/1.0.0/)
- NSRR cohorts used for YASA (CCSHS, CFS, CHAT, HomePAP, MESA, MrOS, SHHS) — [Vallat & Walker 2021](https://elifesciences.org/articles/70092); SHHS and MESA "require access through sleepdata.org", CinC available from physionet.org — [Sridhar et al. 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC7441407/); MASS access "requires requesting permission" — [DeepSleepNet GitHub](https://github.com/akaraspt/deepsleepnet); of RobustSleepNet's eight datasets, DODO, DODH, Sleep-EDFx and CAP are open access, the others need a request — [RobustSleepNet GitHub](https://github.com/Dreem-Organization/RobustSleepNet)
- MESA used as the channel-reduction benchmark (350-subject subsample; 3 EEG + 1 ECG) — [Mehdi et al. 2026](https://arxiv.org/html/2609.22105v1)
- BIDSleep (PhysioNet, open, ODC-BY): 47 healthy adults, 253 nights, Apple Watch instantaneous HR (~0.2 Hz) + 3-axis accelerometry, 30-s labels from Dreem 2 EEG auto-scoring reviewed by one expert — not PSG; v1.0.0 May 2026, v1.0.1 Sep 2026 — [PhysioNet bidsleep-dataset](https://physionet.org/content/bidsleep-dataset/1.0.0/)
- DREAMT (PhysioNet, restricted access): 100 participants, Empatica E4 wrist wearable + clinical PSG with technician annotations; v2.2.0 June 2026 — [PhysioNet DREAMT](https://physionet.org/content/dreamt/)
- Muse-S + PSG (47 nights) was collected at University of Ottawa but the paper does not state public availability — [Sleep Advances 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12782022/)
- Consumer-device staging in the Mehdi benchmark and others is compared to expert inter-scorer agreement of accuracy 0.80–0.85, κ 0.70–0.75 — [Gillard et al. 2024 via research.google](https://research.google/pubs/sleep-staging-classification-from-wearable-signals-using-deep-learning/)

### Inferences
- BOAS is the single most useful open benchmark for a 2-frontal-channel 256 Hz device: montage and sampling rate match Muse's Fp1/Fp2 closely enough for transfer experiments, and it has consensus PSG labels.
- A small project can report Sleep-EDFx numbers only as a sanity check of code, since its Fpz-Cz derivation is not a forehead-only montage.

### Gaps
- BOAS license, exact file format (BIDS/EDF) and subject count were not confirmed (OpenNeuro page is JavaScript-only; vendor page omits them).
- No open dataset pairs Muse (any generation) with PSG.
- Availability of the Donders2022 and the 135-night ZMax validation corpus is not documented.

## Key Question 6: Standards and formats (EDF/EDF+, BIDS-EEG, hypnogram/annotation formats, MNE Raw, LSL) and what open sleep tools expect as input

### Takeaway
Open stagers converge on EDF/EDF+ or MNE `Raw` input with internal resampling (YASA 100 Hz, U-Sleep 128 Hz, ezscore-f 64 Hz), and hypnograms are exchanged either as EDF+ annotation TALs with standard texts ("Sleep stage W/N1/…") or as per-epoch arrays/probabilities; BIDS-EEG standardises raw EEG containers and channel typing but has no sleep-stage annotation vocabulary of its own.

### Cited Findings
- EDF+ adds an "EDF Annotations" signal holding Time-stamped Annotation Lists (TALs: onset, optional duration, UTF-8 text), supports discontinuous recordings (EDF+C vs EDF+D), stays readable by EDF viewers, allows derived results such as sleep stages in a separate synchronized file, and defines standard hypnogram texts such as "Sleep stage W" and "Sleep stage N1" — [EDF+ specification](https://www.edfplus.info/specs/edfplus.html)
- BIDS-EEG raw formats: `.edf` (EDF+ permitted, recommended), BrainVision triplet (recommended), EEGLAB `.set` (discouraged), Biosemi `.bdf`; required sidecar fields `EEGReference`, `SamplingFrequency`, `PowerLineFrequency`, `SoftwareFilters`, `TaskName`; `channels.tsv` columns `name`, `type` (EEG, EOG, ECG, EMG, MISC, TRIG…), `units`; the EEG page does not define sleep-stage annotations — [BIDS EEG specification](https://bids-specification.readthedocs.io/en/stable/modality-specific-files/electroencephalography.html)
- YASA: input is an MNE `BaseRaw`, auto-downsampled to 100 Hz, microvolts assumed; output hypnogram + probability table — [yasa.SleepStaging docs](https://yasa-sleep.org/generated/yasa.SleepStaging.html)
- U-Sleep: EDF or HDF5 upload; channels resampled to 128 Hz; stage output at user-chosen frequency — [Perslev et al. 2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8050216/); `ut extract` stores 128 Hz HDF5 — [U-Time GitHub](https://github.com/perslev/U-Time)
- ezscore-f: MNE `Raw` in volts with channels named `eegl`/`eegr`, resampled to 64 Hz; loaders for ZMax paired EDFs, two-channel EDF, and raw `.cgx` — [ezscore GitHub](https://github.com/coonwg1/ezscore)
- Dreem DOD: HDF5 with `Hypnogram` (-1, 0–4) and `Signals` groups; example configs resample to 100 Hz — [dreem-learning-open](https://github.com/Dreem-Organization/dreem-learning-open)
- Luna: EDF/EDF+ input, command-line engine with Python (`lunapi`) and R interfaces — [luna-base GitHub](https://github.com/remnrem/luna-base)
- Sleep-EDFx hypnograms are distributed as EDF+ — [PhysioNet sleep-edfx](https://physionet.org/content/sleep-edfx/1.0.0/)
- LSL: Portiloop streams its EEG over LSL alongside CSV recording — [portiloop-software GitHub](https://github.com/Portiloop/portiloop-software); Dreamento records ZMax via Hypnodyne's HDServer socket rather than LSL and stores per-second sample counts because wireless sampling fluctuates around 256 Hz — [Jafarzadeh Esfahani et al. 2022](https://arxiv.org/abs/2207.03977v2)
- sleepecg provides downloaders/readers for NSRR and PhysioNet datasets (reading MESA/SHHS needs `edfio`) — [sleepecg docs](https://sleepecg.readthedocs.io/)

### Inferences
- Exporting EDF+ with standard hypnogram texts plus an MNE-loadable raw file is sufficient to run YASA, U-Sleep (web), Luna and ezscore-f on the same night, which makes EDF+ the pragmatic interchange target for a Muse pipeline.
- Probability/hypnodensity outputs (YASA `proba`, U-Sleep high-frequency stages, Dreamento hypnodensity, ezscore `ezpredict`) have no shared file format; comparisons across tools are done at the 30-s label level.

### Gaps
- Luna's `.annot` and NSRR XML annotation formats could not be fetched (server errors); their specifics are not documented here.
- No BIDS extension or community standard for sleep-stage annotations was found in the sources consulted.
