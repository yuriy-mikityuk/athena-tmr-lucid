import datetime as dt
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import muse_athena_protocol as proto
import pandas as pd
from muse_raw_stream import MuseRawStream

from muse_tmr.annotations import (
    RemAnnotation,
    build_rem_annotation,
    export_rem_annotations,
    load_rem_annotations,
    rem_training_rows,
    validate_rem_label,
)
from muse_tmr.cli.main import main
from muse_tmr.features.epochs import SleepEpoch
from muse_tmr.models import RemPrediction


def empty_epoch(index=0):
    return SleepEpoch(
        index=index,
        start_time=1000.0 + index * 30.0,
        end_time=1030.0 + index * 30.0,
        frames=(),
        modality_counts={},
        sample_counts={},
        coverage={"eeg": 0.0, "imu": 0.0, "ppg": 0.0, "heart_rate": 0.0},
        quality_flags=("missing_eeg", "missing_imu", "missing_ppg", "missing_heart_rate"),
    )


def build_tag_packet(first_tag, first_data):
    header = bytearray(14)
    header[9] = first_tag
    return bytes(header) + first_data


def write_synthetic_recording(recording_dir: Path) -> None:
    recording_dir.mkdir(parents=True, exist_ok=True)
    raw_path = recording_dir / "raw_amused.bin"
    stream = MuseRawStream(str(raw_path))
    stream.open_write()
    base_time = stream.session_start
    stream.write_packet(build_tag_packet(proto.TAG_EEG_4CH, bytes(28)), base_time)
    stream.write_packet(
        build_tag_packet(proto.TAG_ACCGYRO, bytes(36)),
        base_time + dt.timedelta(seconds=10),
    )
    stream.write_packet(
        build_tag_packet(proto.TAG_OPTICS_8CH, bytes(60)),
        base_time + dt.timedelta(seconds=40),
    )
    stream.close()
    (recording_dir / "metadata.json").write_text(
        json.dumps({"source": {"source_name": "amused", "device_name": "Muse Test"}}),
        encoding="utf-8",
    )


class TestRemAnnotations(unittest.TestCase):
    def test_build_annotation_overlays_prediction_features(self):
        prediction = RemPrediction(
            probability=0.75,
            reason_codes=("eeg_eye_movement_support",),
            feature_scores={"eye_movement_proxy": 1.0},
            feature_values={"eye_movement_proxy": 0.25},
            source="heuristic",
        )

        row = build_rem_annotation(
            empty_epoch(),
            prediction=prediction,
            recording_id="session-a",
        )
        payload = row.to_dict()

        self.assertEqual(row.label, "unknown")
        self.assertEqual(payload["p_rem"], 0.75)
        self.assertEqual(payload["reason_codes"], "eeg_eye_movement_support")
        self.assertEqual(payload["feature_score_eye_movement_proxy"], 1.0)
        self.assertEqual(payload["feature_value_eye_movement_proxy"], 0.25)

    def test_labels_are_validated(self):
        self.assertEqual(validate_rem_label("Probable_REM"), "probable_rem")
        with self.assertRaises(ValueError):
            validate_rem_label("rem")

    def test_csv_and_json_roundtrip_preserves_unknown_label(self):
        rows = (
            RemAnnotation(
                recording_id="session-a",
                epoch_index=0,
                start_time=1000.0,
                end_time=1030.0,
                duration_seconds=30.0,
                label="unknown",
                p_rem=0.4,
                reason_codes=("limited_feature_support",),
                feature_scores={"stillness": 1.0},
                feature_values={"stillness_score": 0.99},
                prediction_source="heuristic",
            ),
            RemAnnotation(
                recording_id="session-a",
                epoch_index=1,
                start_time=1030.0,
                end_time=1060.0,
                duration_seconds=30.0,
                label="probable_rem",
                p_rem=0.8,
                feature_scores={"eye_movement_proxy": 1.0},
                feature_values={"eye_movement_proxy": 0.2},
                prediction_source="heuristic",
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = export_rem_annotations(rows, tmp_path / "labels.csv")
            json_path = export_rem_annotations(rows, tmp_path / "labels.json")

            csv_rows = load_rem_annotations(csv_path)
            json_rows = load_rem_annotations(json_path)

        self.assertEqual([row.label for row in csv_rows], ["unknown", "probable_rem"])
        self.assertEqual([row.label for row in json_rows], ["unknown", "probable_rem"])
        self.assertEqual(csv_rows[0].reason_codes, ("limited_feature_support",))

    def test_training_rows_exclude_unknown_by_default(self):
        rows = (
            RemAnnotation(
                recording_id="session-a",
                epoch_index=0,
                start_time=1000.0,
                end_time=1030.0,
                duration_seconds=30.0,
                label="unknown",
            ),
            RemAnnotation(
                recording_id="session-a",
                epoch_index=1,
                start_time=1030.0,
                end_time=1060.0,
                duration_seconds=30.0,
                label="wake",
            ),
        )

        training = rem_training_rows(rows)
        with_unknown = rem_training_rows(rows, include_unknown=True)

        self.assertEqual(len(training), 1)
        self.assertEqual(training[0]["label"], "wake")
        self.assertEqual(len(with_unknown), 2)

    def test_cli_generates_annotation_template_from_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            recording_dir = Path(tmp) / "recording"
            output_path = Path(tmp) / "annotations.csv"
            write_synthetic_recording(recording_dir)

            with redirect_stdout(io.StringIO()):
                exit_code = main([
                    "annotate-template",
                    str(recording_dir),
                    "--output",
                    str(output_path),
                ])
            frame = pd.read_csv(output_path)

        self.assertEqual(exit_code, 0)
        self.assertGreaterEqual(len(frame), 1)
        self.assertTrue(set(frame["label"]) == {"unknown"})
        self.assertIn("p_rem", frame.columns)
        self.assertIn("reason_codes", frame.columns)


if __name__ == "__main__":
    unittest.main()
