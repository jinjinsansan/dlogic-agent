#!/usr/bin/env python3
"""Run only the backend v2 predictions router for local replay backtests.

The full backend main.py may skip v2 route registration when optional
production dependencies are missing. This lightweight app exposes only:
    POST /api/v2/predictions/newspaper
"""
from __future__ import annotations

import os
import sys
import importlib.util
from pathlib import Path

from fastapi import FastAPI


BACKEND_DIR = Path(os.environ.get("DLOGIC_BACKEND_DIR", r"E:\dev\Cusor\chatbot\uma\backend"))
sys.path.insert(0, str(BACKEND_DIR))

predictions_path = BACKEND_DIR / "api" / "v2" / "predictions.py"
spec = importlib.util.spec_from_file_location("backend_v2_predictions", predictions_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not load {predictions_path}")
predictions_router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(predictions_router)


app = FastAPI(title="DLogic predictions-only replay API")
app.include_router(predictions_router.router, prefix="/api/v2/predictions")


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "app": "predictions-only"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
