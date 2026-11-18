import csv
import hashlib
import math
from pathlib import Path
from typing import Any


FEATURES = (
    "meanDb",
    "spreadDb",
    "strongReturnRatio",
    "weakReturnRatio",
    "peakRangeFraction",
    "validCoverage",
)


def parse_ping(fields: list[str]) -> dict[str, Any] | None:
    try:
        sample_count = int(fields[12])
        if sample_count <= 0:
            return None

        valid: list[tuple[int, float]] = []
        for index, raw_value in enumerate(fields[13 : 13 + sample_count]):
            value = float(raw_value)
            if math.isfinite(value) and -200 < value < 20:
                valid.append((index, value))
        if len(valid) < 12:
            return None

        values = [value for _, value in valid]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        peak_index, _ = max(valid, key=lambda sample: sample[1])
        feature_values = {
            "meanDb": mean,
            "spreadDb": math.sqrt(variance),
            "strongReturnRatio": sum(value > -60 for value in values) / len(values),
            "weakReturnRatio": sum(value < -75 for value in values) / len(values),
            "peakRangeFraction": peak_index / max(sample_count - 1, 1),
            "validCoverage": len(valid) / sample_count,
        }
        if not all(math.isfinite(value) for value in feature_values.values()):
            return None

        range_start = float(fields[10])
        range_stop = float(fields[11])
        range_fraction = feature_values["peakRangeFraction"]
        range_meters = range_start + (range_stop - range_start) * range_fraction
        latitude = float(fields[6])
        longitude = float(fields[7])
        location = (
            {"lat": latitude, "lon": longitude}
            if math.isfinite(latitude)
            and math.isfinite(longitude)
            and abs(latitude) <= 90
            and abs(longitude) <= 180
            else None
        )
        distance = float(fields[1])
        return {
            "pingIndex": int(fields[0]),
            "distanceNm": distance if math.isfinite(distance) else None,
            "acquiredAt": f"{fields[3].strip()}T{fields[4].strip()}Z",
            "location": location,
            "rangeMeters": range_meters,
            "features": feature_values,
        }
    except (IndexError, ValueError, OverflowError):
        return None


def load_pings(csv_path: Path) -> tuple[list[dict[str, Any]], int]:
    samples: list[dict[str, Any]] = []
    skipped_rows = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        header = next(reader, [])
        if not header or header[0].strip() != "Ping_index":
            raise ValueError("The dataset is not the expected NOAA processed EK60 CSV.")
        for fields in reader:
            if not fields or not any(value.strip() for value in fields):
                continue
            sample = parse_ping(fields)
            if sample is None:
                skipped_rows += 1
            else:
                samples.append(sample)

    if len(samples) < 100:
        raise ValueError(f"The NOAA dataset has too few valid pings ({len(samples)}).")
    return samples, skipped_rows


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
