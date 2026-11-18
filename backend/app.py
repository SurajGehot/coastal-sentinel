import asyncio
import csv
import json
from collections import deque
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from backend.data import FEATURES
from backend.train import MODEL_PATH, METADATA_PATH, SPLIT_DIR


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
HISTORY_LIMIT = 180
REPLAY_INTERVAL_SECONDS = 1.2
history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LIMIT)
clients: set[asyncio.Queue[str]] = set()
running = True
sequence = 0
replay_position = 0
test_samples: list[dict[str, Any]] = []
artifact: dict[str, Any] = {}
started_at = datetime.now(timezone.utc).isoformat()


def load_test_samples() -> list[dict[str, Any]]:
    test_path = SPLIT_DIR / "test.csv"
    if not MODEL_PATH.is_file() or not METADATA_PATH.is_file() or not test_path.is_file():
        raise RuntimeError("Trained model or data splits are missing. Run `npm run train` first.")
    with test_path.open("r", encoding="utf-8", newline="") as source:
        result = []
        for row in csv.DictReader(source):
            latitude = _optional_float(row["latitude"])
            longitude = _optional_float(row["longitude"])
            result.append(
                {
                    "pingIndex": int(row["pingIndex"]),
                    "distanceNm": _optional_float(row["distanceNm"]),
                    "acquiredAt": row["acquiredAt"],
                    "location": (
                        {"lat": latitude, "lon": longitude}
                        if latitude is not None and longitude is not None
                        else None
                    ),
                    "rangeMeters": float(row["rangeMeters"]),
                    "features": {feature: float(row[feature]) for feature in FEATURES},
                }
            )
    if not result:
        raise RuntimeError("The held-out NOAA test split contains no pings.")
    return result


def _optional_float(value: str) -> float | None:
    return float(value) if value else None


def ensure_model_loaded() -> None:
    global artifact, test_samples
    artifact = joblib.load(MODEL_PATH)
    test_samples = load_test_samples()


ensure_model_loaded()


def current_stats() -> dict[str, Any]:
    metadata = artifact["metadata"]
    average_score = (
        sum(sample["score"] for sample in history) / len(history) if history else 0
    )
    return {
        "status": "live" if running else "paused",
        "samplesAnalyzed": sequence,
        "detections": sum(sample["anomaly"] for sample in history),
        "averageScore": round(average_score, 3),
        "model": metadata["algorithm"],
        "threshold": metadata["threshold"]["anomalyPercentile"],
        "trainingSamples": metadata["split"]["train"]["count"],
        "validationSamples": metadata["split"]["validation"]["count"],
        "testSamples": len(test_samples),
        "dataset": metadata["source"]["name"],
        "feedMode": "NOAA held-out test replay",
        "replayPosition": replay_position,
        "replayTotal": len(test_samples),
        "rangeMinMeters": min(sample["rangeMeters"] for sample in test_samples),
        "rangeMaxMeters": max(sample["rangeMeters"] for sample in test_samples),
        "startedAt": started_at,
    }


def predict(sample: dict[str, Any]) -> dict[str, Any]:
    matrix = np.asarray(
        [[sample["features"][feature] for feature in FEATURES]], dtype=np.float64
    )
    raw_score = float(artifact["estimator"].score_samples(matrix)[0])
    ordered_training_scores = artifact["trainingScores"]
    anomaly_score = float(
        1 - np.searchsorted(ordered_training_scores, raw_score, side="right")
        / len(ordered_training_scores)
    )
    threshold_raw = artifact["metadata"]["threshold"]["validationRawScoreQuantile"]
    return {
        **sample,
        "id": f"PING-{sequence + 1:06d}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sourcePingIndex": sample["pingIndex"],
        "score": round(anomaly_score, 4),
        "anomaly": raw_score <= threshold_raw,
    }


def publish(event: str, payload: dict[str, Any]) -> None:
    message = f"event: {event}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"
    for queue in tuple(clients):
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(message)


async def replay_loop() -> None:
    global sequence, replay_position
    first_outlier = None
    for index, sample in enumerate(test_samples):
        if predict(sample)["anomaly"]:
            first_outlier = index
            break
    if first_outlier is not None:
        replay_position = max(0, first_outlier - 4)

    while True:
        if running:
            current = predict(test_samples[replay_position])
            sequence += 1
            current["id"] = f"PING-{sequence:06d}"
            replay_position = (replay_position + 1) % len(test_samples)
            history.appendleft(current)
            publish("sample", current)
            if current["anomaly"]:
                publish("detection", current)
            publish("stats", current_stats())
        await asyncio.sleep(REPLAY_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(replay_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Coastal Sentinel API", version="2.0.0", lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, **current_stats()}


@app.get("/api/history")
async def get_history() -> dict[str, Any]:
    return {"samples": list(history), "stats": current_stats()}


@app.get("/api/model")
async def model_info() -> dict[str, Any]:
    return artifact["metadata"]


@app.get("/api/events")
async def events() -> StreamingResponse:
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=32)

    async def stream() -> AsyncIterator[str]:
        clients.add(queue)
        try:
            yield f"event: stats\ndata: {json.dumps(current_stats())}\n\n"
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            clients.discard(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/stream/start")
async def start_stream() -> dict[str, Any]:
    global running
    running = True
    stats = current_stats()
    publish("stats", stats)
    return stats


@app.post("/api/stream/stop")
async def stop_stream() -> dict[str, Any]:
    global running
    running = False
    stats = current_stats()
    publish("stats", stats)
    return stats


@app.get("/detections")
async def detections_page() -> FileResponse:
    return FileResponse(WEB_ROOT / "detections.html")


@app.get("/transect")
async def transect_page() -> FileResponse:
    return FileResponse(WEB_ROOT / "transect.html")


@app.get("/model")
async def model_page() -> FileResponse:
    return FileResponse(WEB_ROOT / "model.html")


@app.get("/{asset_path:path}")
async def static_files(asset_path: str) -> FileResponse:
    requested = asset_path or "index.html"
    file_path = (WEB_ROOT / requested).resolve()
    if not file_path.is_relative_to(WEB_ROOT.resolve()):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(file_path)
