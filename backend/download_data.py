import shutil
import tempfile
import urllib.request
from pathlib import Path


DATASET_URL = (
    "https://ncei-wcsd-archive.s3-us-west-2.amazonaws.com/data/processed/SH1305/"
    "18kHz/SaKe2013-D20130523-T080854_to_SaKe2013-D20130523-T085643.csv"
)
DATASET_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "raw"
    / "noaa-sh1305-18khz.csv"
)
MINIMUM_FILE_SIZE = 1000


def download_dataset(destination: Path = DATASET_PATH) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size >= MINIMUM_FILE_SIZE:
        with destination.open("r", encoding="utf-8-sig") as existing:
            if existing.readline().startswith("Ping_index,"):
                return destination

    request = urllib.request.Request(
        DATASET_URL,
        headers={"User-Agent": "CoastalSentinel/1.0"},
    )
    temporary_path: Path | None = None
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/csv" not in content_type.lower():
                raise ValueError(
                    f"Expected NOAA to return CSV data, received {content_type!r}."
                )
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f"{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                shutil.copyfileobj(response, temporary)

        if temporary_path.stat().st_size < MINIMUM_FILE_SIZE:
            raise ValueError("The NOAA download is unexpectedly small.")
        with temporary_path.open("r", encoding="utf-8-sig") as downloaded:
            if not downloaded.readline().startswith("Ping_index,"):
                raise ValueError("Downloaded file is not the expected NOAA EK60 CSV.")
        temporary_path.replace(destination)
        return destination
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


if __name__ == "__main__":
    downloaded_path = download_dataset()
    print(f"NOAA sonar dataset ready: {downloaded_path}")
    print(f"Size: {downloaded_path.stat().st_size:,} bytes")
