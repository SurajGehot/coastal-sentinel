import csv
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest

from backend.data import FEATURES, load_pings, sha256_file


ROOT = Path(__file__).resolve().parents[1]
RAW_DATASET = ROOT / "data" / "raw" / "noaa-sh1305-18khz.csv"
SPLIT_DIR = ROOT / "data" / "splits"
MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "sonar_isolation_forest.joblib"
METADATA_PATH = MODEL_DIR / "model_metadata.json"
TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
VALIDATION_ALERT_RATE = 0.05
EMBARGO_PINGS = 10
MODEL_PARAMS = {
    "n_estimators": 300,
    "max_samples": 256,
    "contamination": "auto",
    "random_state": 47,
    "n_jobs": -1,
}


def chronological_split(
    samples: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    train_end = int(len(samples) * TRAIN_FRACTION)
    validation_end = int(len(samples) * (TRAIN_FRACTION + VALIDATION_FRACTION))
    train = samples[:train_end]
    validation_start = min(train_end + EMBARGO_PINGS, validation_end)
    test_start = min(validation_end + EMBARGO_PINGS, len(samples))
    validation = samples[validation_start:validation_end]
    test = samples[test_start:]
    split = {
        "strategy": "chronological with 10-ping embargo between partitions",
        "train": {"start": 0, "endExclusive": train_end, "count": len(train)},
        "validation": {
            "start": validation_start,
            "endExclusive": validation_end,
            "count": len(validation),
        },
        "test": {"start": test_start, "endExclusive": len(samples), "count": len(test)},
        "embargoedPings": (validation_start - train_end) + (test_start - validation_end),
    }
    if min(len(train), len(validation), len(test)) < 20:
        raise ValueError("The chronological split must leave at least 20 pings per partition.")
    return train, validation, test, split


def write_split(path: Path, samples: list[dict[str, Any]]) -> None:
    columns = [
        "pingIndex",
        "acquiredAt",
        "distanceNm",
        "latitude",
        "longitude",
        "rangeMeters",
        *FEATURES,
    ]
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for sample in samples:
            location = sample["location"] or {}
            writer.writerow(
                {
                    "pingIndex": sample["pingIndex"],
                    "acquiredAt": sample["acquiredAt"],
                    "distanceNm": sample["distanceNm"],
                    "latitude": location.get("lat"),
                    "longitude": location.get("lon"),
                    "rangeMeters": sample["rangeMeters"],
                    **sample["features"],
                }
            )


def feature_matrix(samples: list[dict[str, Any]]) -> np.ndarray:
    return np.asarray(
        [[sample["features"][feature] for feature in FEATURES] for sample in samples],
        dtype=np.float64,
    )


def train_model() -> dict[str, Any]:
    if not RAW_DATASET.is_file():
        raise FileNotFoundError(
            f"NOAA source file not found at {RAW_DATASET}. Run `npm run setup:data` first."
        )

    samples, skipped_rows = load_pings(RAW_DATASET)
    train, validation, test, split = chronological_split(samples)
    train_features = feature_matrix(train)
    validation_features = feature_matrix(validation)
    test_features = feature_matrix(test)

    estimator = IsolationForest(**MODEL_PARAMS)
    estimator.fit(train_features)
    training_scores = estimator.score_samples(train_features)
    validation_scores = estimator.score_samples(validation_features)
    threshold_raw = float(
        np.quantile(validation_scores, VALIDATION_ALERT_RATE, method="linear")
    )
    threshold_percentile = float(
        1
        - np.searchsorted(
            np.sort(training_scores), threshold_raw, side="right"
        )
        / len(training_scores)
    )

    def evaluate(partition: list[dict[str, Any]], matrix: np.ndarray) -> dict[str, Any]:
        scores = estimator.score_samples(matrix)
        percentile_scores = 1 - np.searchsorted(
            np.sort(training_scores), scores, side="right"
        ) / len(training_scores)
        return {
            "samples": len(partition),
            "alertRate": float(np.mean(scores <= threshold_raw)),
            "medianAnomalyPercentile": float(np.median(percentile_scores)),
            "p95AnomalyPercentile": float(np.quantile(percentile_scores, 0.95)),
        }

    validation_metrics = evaluate(validation, validation_features)
    test_metrics = evaluate(test, test_features)
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    write_split(SPLIT_DIR / "train.csv", train)
    write_split(SPLIT_DIR / "validation.csv", validation)
    write_split(SPLIT_DIR / "test.csv", test)

    metadata = {
        "algorithm": "Isolation Forest",
        "implementation": "scikit-learn",
        "selectionNote": (
            "Selected as a tree-based unsupervised outlier detector for tabular sonar features. "
            "No debris labels exist, so supervised accuracy or debris-classification performance "
            "cannot be measured or claimed."
        ),
        "parameters": MODEL_PARAMS,
        "features": list(FEATURES),
        "threshold": {
            "anomalyPercentile": threshold_percentile,
            "validationRawScoreQuantile": threshold_raw,
            "targetValidationAlertRate": VALIDATION_ALERT_RATE,
            "calibration": (
                f"lowest {VALIDATION_ALERT_RATE:.0%} validation score_samples"
            ),
        },
        "source": {
            "name": "NOAA NCEI SH1305 EK60 18 kHz processed water-column sonar",
            "path": str(RAW_DATASET.relative_to(ROOT)),
            "sha256": sha256_file(RAW_DATASET),
            "usablePings": len(samples),
            "skippedRows": skipped_rows,
        },
        "split": split,
        "evaluation": {
            "validation": validation_metrics,
            "test": test_metrics,
            "accuracy": None,
            "accuracyNote": (
                "The archive is unlabeled and contains no verified ghost-net or marine-debris "
                "targets; accuracy is undefined."
            ),
        },
        "versions": {
            "python": platform.python_version(),
            "scikitLearn": sklearn.__version__,
            "numpy": np.__version__,
        },
        "trainedAt": datetime.now(timezone.utc).isoformat(),
    }
    artifact = {
        "estimator": estimator,
        "trainingScores": np.sort(training_scores),
        "thresholdRaw": threshold_raw,
        "metadata": metadata,
    }
    joblib.dump(artifact, MODEL_PATH, compress=3)
    METADATA_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


if __name__ == "__main__":
    result = train_model()
    print(json.dumps(result, indent=2))
