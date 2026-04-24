# Testing Guide

## Runpod Requests tab payloads

### Text

```json
{
  "input": {
    "mode": "text",
    "text_a": "AI policy should focus on transparency, safety, and measured rollout.",
    "text_b": "AI policy must move fast to preserve innovation while managing risk."
  }
}
```

### Audio URLs

```json
{
  "input": {
    "mode": "audio",
    "media_url_a": "https://example.com/a.wav",
    "media_url_b": "https://example.com/b.wav"
  }
}
```

### Video URLs

```json
{
  "input": {
    "mode": "video",
    "media_url_a": "https://example.com/a.mp4",
    "media_url_b": "https://example.com/b.mp4"
  }
}
```

## Vercel preview checks

1. Open `/launch`
2. Confirm Turnstile loads
3. Submit text comparison -> `/api/diff/start`
4. Confirm `/run` polls `/api/diff/status/:jobId`
5. Confirm `/results` renders output
6. Repeat with audio/video upload flow once Blob uploader wiring is enabled
7. Confirm rate limits:
   - text: 10/day/IP
   - media: 5/day/IP
   - burst: short per-minute limit
