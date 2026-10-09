#!/usr/bin/env python3
"""Run the API: python scripts/serve_api.py  (host/port from env API_HOST / API_PORT)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("lpc_regwatch.api.app:app", host=os.getenv("API_HOST", "0.0.0.0"), port=int(os.getenv("API_PORT", "8000")), reload=False)
