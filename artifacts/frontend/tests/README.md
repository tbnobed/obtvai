# Live dictation regression checks

Run these from the workspace root.

## Deterministic text and audio tests

```bash
pnpm --filter @workspace/frontend exec tsx src/components/voice-text-region.test.ts
node --experimental-strip-types --test artifacts/frontend/src/hooks/audio-capture.test.ts
pnpm run typecheck
```

## Browser integration

Start the frontend and mock API workflows, then start a test browser in a separate terminal:

```bash
chromium --headless --no-sandbox --disable-dev-shm-usage \
  --autoplay-policy=no-user-gesture-required \
  --remote-debugging-port=9222 --user-data-dir=/tmp/live-voice-browser about:blank
```

Run:

```bash
node artifacts/frontend/tests/live-voice.browser.mjs
```

This is a **mock-preview test**, not a production test. It uses the documented
mock login, real Web Audio capture/encoding with a synthetic microphone signal,
and mocked speech HTTP responses. It does not test speech recognition accuracy.
It checks live controlled-input updates before Stop, final refinement,
one-in-flight backpressure, cancellation, late permission/navigation cleanup,
manual-edit preservation, error handling, and mobile AI prompt layout. It saves
the mobile capture to `/tmp/live-voice-mobile.png`.

The defaults are `APP_TEST_URL=http://localhost:80` and
`BROWSER_DEBUG_URL=http://127.0.0.1:9222`. Stop the test Chromium when finished.

## Backend safety tests

With the API's Python requirements available:

```bash
cd services/api
PYTHONPATH=. python -m unittest tests.test_speech_transcription
```

This checks decoded audio limits, partial silence versus malformed audio,
partial/final inference options, disconnect and timeout recovery, and temporary
file cleanup. Dependency-light checkouts skip tests requiring FastAPI or NumPy;
run with the real API dependencies for complete coverage.