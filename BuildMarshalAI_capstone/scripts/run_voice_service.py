"""Run the local Whisper voice service (backend/voice_service.py).

The backend forwards the chat microphone's recordings, and uploaded audio
documents, to this service. START-BUILDMARSHAL.ps1 starts it; to run it by hand:

    python scripts/run_voice_service.py            # http://127.0.0.1:8903
    python scripts/run_voice_service.py --port 8904

Needs ``openai-whisper`` and ``ffmpeg`` on PATH. The first start downloads the
Whisper ``base`` model (about 140 MB) into .buildmarshal_runtime/whisper_models.
"""
from __future__ import annotations

import argparse
import importlib.util
import logging
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODEL_DIR = REPO / ".buildmarshal_runtime" / "whisper_models"
sys.path.insert(0, str(REPO / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    # Loopback only: the backend on this machine is the service's one client.
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8903)
    args = parser.parse_args()

    missing = [name for name in ("whisper", "multipart", "uvicorn")
               if importlib.util.find_spec(name) is None]
    if missing:
        raise SystemExit(f"Missing Python packages: {', '.join(missing)}. "
                         "Install them with: pip install openai-whisper python-multipart uvicorn")
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg is not on PATH; Whisper needs it to read recordings. "
                         "Install it with: winget install Gyan.FFmpeg")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    import uvicorn
    from voice_service import create_app, whisper_transcriber

    transcribe, info = whisper_transcriber(MODEL_DIR)
    uvicorn.run(create_app(transcribe, info), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    sys.exit(main())
