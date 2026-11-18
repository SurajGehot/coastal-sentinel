import csv
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app import artifact, predict, test_samples
from backend.download_data import download_dataset
from backend.data import FEATURES, load_pings
from backend.train import MODEL_PATH, METADATA_PATH, SPLIT_DIR, RAW_DATASET


class ModelPipelineTests(unittest.TestCase):
    def test_artifact_is_persisted_and_identifies_python_isolation_forest(self):
        self.assertTrue(MODEL_PATH.is_file())
        self.assertTrue(METADATA_PATH.is_file())
        self.assertEqual(artifact["metadata"]["algorithm"], "Isolation Forest")
        self.assertEqual(artifact["metadata"]["implementation"], "scikit-learn")
        self.assertIsNone(artifact["metadata"]["evaluation"]["accuracy"])

    def test_saved_partitions_are_chronological_and_non_overlapping(self):
        ping_indexes = {}
        for name in ("train", "validation", "test"):
            with (SPLIT_DIR / f"{name}.csv").open(
                "r", encoding="utf-8", newline=""
            ) as source:
                ping_indexes[name] = [
                    int(row["pingIndex"]) for row in csv.DictReader(source)
                ]

        self.assertFalse(set(ping_indexes["train"]) & set(ping_indexes["validation"]))
        self.assertFalse(set(ping_indexes["train"]) & set(ping_indexes["test"]))
        self.assertFalse(set(ping_indexes["validation"]) & set(ping_indexes["test"]))
        self.assertLess(max(ping_indexes["train"]), min(ping_indexes["validation"]))
        self.assertLess(max(ping_indexes["validation"]), min(ping_indexes["test"]))

    def test_website_predicts_only_features_from_held_out_test_data(self):
        sample = test_samples[0]
        result = predict(sample)

        self.assertEqual(result["sourcePingIndex"], sample["pingIndex"])
        self.assertTrue(0 <= result["score"] <= 1)
        self.assertIsInstance(result["anomaly"], bool)
        self.assertEqual(set(sample["features"]), set(FEATURES))

    def test_validation_calibrated_model_flags_outliers_in_unseen_test_partition(self):
        predictions = [predict(sample) for sample in test_samples]

        self.assertGreater(sum(item["anomaly"] for item in predictions), 0)
        self.assertLess(
            abs(
                sum(item["anomaly"] for item in predictions) / len(predictions)
                - artifact["metadata"]["evaluation"]["test"]["alertRate"]
            ),
            1 / len(predictions),
        )

    def test_raw_noaa_rows_parse_into_expected_feature_vector(self):
        samples, skipped = load_pings(RAW_DATASET)

        self.assertGreater(len(samples), 2000)
        self.assertEqual(len(samples), 2545)
        self.assertEqual(skipped, 3)
        self.assertEqual(set(samples[0]["features"]), set(FEATURES))

    def test_dataset_download_is_python_owned_and_validates_csv(self):
        body = b"Ping_index,Sample_count\n1,12\n"

        class FakeResponse(io.BytesIO):
            headers = {"Content-Type": "text/csv"}

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "sonar.csv"
            with patch("backend.download_data.urllib.request.urlopen") as open_url:
                open_url.return_value = FakeResponse(body * 100)
                result = download_dataset(destination)

            self.assertEqual(result, destination)
            self.assertTrue(destination.read_text(encoding="utf-8").startswith("Ping_index,"))


if __name__ == "__main__":
    unittest.main()
