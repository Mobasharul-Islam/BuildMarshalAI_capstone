# BuildMarshalAI Voice Transcription Pipeline

## Purpose

The voice feature turns a short microphone recording into text. It does not answer the question itself.

1. The browser records up to 60 seconds of audio.
2. The frontend posts the recording to the backend (`POST /api/voice/transcribe`).
3. The backend forwards it to the local Whisper voice service and returns the transcript.
4. The transcript lands in the chat input (or the Onboarding command box) for review.
5. When the user presses **Send**, the backend runs retrieval and generates the grounded answer.

Whisper runs in its own process on the same machine, so it never shares memory with ColPali, and a voice failure cannot take retrieval down. The browser never talks to it directly.

## The local voice service

`backend/voice_service.py` is the service. `scripts/run_voice_service.py` runs it:

```
python scripts/run_voice_service.py            # http://127.0.0.1:8903
```

- `START-BUILDMARSHAL.ps1` starts it when `openai-whisper` (in `requirements-handover.txt`) and `ffmpeg` are installed, and tells the backend its address through `BUILDMARSHAL_VOICE_URL`. `STOP-BUILDMARSHAL.ps1` stops it.
- It listens on the loopback interface only. The backend on the same machine is its only client, so it has no CORS and no tunnel.
- The Whisper `base` model is kept in `.buildmarshal_runtime/whisper_models`. The first start downloads it (about 140 MB).
- A backend started without `BUILDMARSHAL_VOICE_URL` uses `http://127.0.0.1:8903`.

**Settings → Voice input** reports whether the service is running (from `voice` in `GET /api/health`). There is nothing to configure per account.

The Kaggle/ngrok voice notebook and the per-account *Voice Service URL* setting were removed. Database migration 2 deleted the stored URLs, and an old client that still sends one is ignored.

## API

### Backend: `POST /api/voice/transcribe`

Signed-in callers only. Multipart field `file`: WebM, WAV, MP3, M4A, MP4, OGG, OPUS, FLAC, or AAC, up to 20 MB.

| Status | Meaning |
|---|---|
| 200 | `text`, `language`, `duration_seconds`, `model` |
| 400 | Empty recording |
| 413 | Over 20 MB |
| 415 | Not an audio type the service accepts |
| 422 | The service refused the recording; `detail` gives its reason (e.g. over 60 s) |
| 503 | The local voice service is not running; `detail` says how to start it |

### Voice service: `GET /api/health`

Reports the model, the device, and the recording limit.

### Voice service: `POST /api/transcribe`

Multipart fields:

- `file`: WebM, WAV, MP3, M4A, MP4, OGG, OPUS, FLAC, or AAC audio
- `language`: optional ISO language code; omit it for automatic detection

Limits: 60 seconds, 20 MB, one transcription at a time. The response contains `text`, the detected `language`, the duration, the processing time, the segments, and the model name.

## Uploaded recordings

Audio files uploaded as documents are transcribed by the same service (`backend/ingestion_formats.py`). The transcript is indexed as ordinary text pages, so what was said is searchable and citable in chat. The original recording is kept and played back from `GET /api/documents/{id}/media`, and the preview shows the transcript under the player.

A recording may not be transcribed because the service is not running or because it refuses the file (60 seconds, 20 MB). In that case the document is kept with its file name and the reason, both in its `transcription` record and in its page text, and nothing is embedded. Longer recordings have to be split before upload.
