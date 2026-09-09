# BuildMarshalAI Voice Transcription Pipeline

## Purpose

The voice feature converts a short microphone recording into text. It does not answer the question itself.

1. The browser records up to 60 seconds of audio.
2. The frontend sends the recording to the separate Whisper service.
3. Whisper returns the transcript.
4. The transcript is placed in the existing chat input for review.
5. When the user presses **Send**, the existing document backend performs retrieval and generates the grounded answer.

This separation keeps Whisper out of the main ColPali/Qwen notebook and gives each service its own disk, GPU, lifecycle, and ngrok URL.

## Kaggle notebook

Use `backend/Voice_Transcription_Service.ipynb` with:

- Internet enabled
- A single T4 GPU
- Kaggle secret `NGROK_AUTH_TOKEN` enabled for this notebook
- Optional **Files only** persistence to retain the downloaded Whisper checkpoint

Run all cells and keep the last cell running. It prints the Voice URL, health URL, and Swagger API documentation URL.

## Frontend setup

Open **Settings** and configure both URLs:

- **Backend URL**: the main ColPali/Qwen document-service ngrok URL
- **Voice Service URL**: the separate Whisper-service ngrok URL

Click the microphone in Marshal Chat to start recording. Click the red stop button when finished. The transcript appears in the text box; review it and press **Send**.

## API

### `GET /api/health`

Reports model, device, CUDA availability, and the recording limit.

### `POST /api/transcribe`

Multipart fields:

- `file`: WebM, WAV, MP3, M4A, MP4, OGG, OPUS, FLAC, or AAC audio
- `language`: optional ISO language code; omit it for automatic detection

Limits:

- Maximum recording duration: 60 seconds
- Maximum upload size: 20 MB
- One GPU transcription at a time

The response contains `text`, detected `language`, audio duration, processing time, segments, and model name.
