---
name: Interactive dictation safety
description: Lifecycle and local-processing decisions for microphone dictation across AI inputs.
---

**Rule:** Treat microphone permission, recording, transcription, and insertion as one owned session. Release the shared session on success and every failure; stale callbacks must not release a newer session or insert text.

**Why:** Permission can resolve after navigation or cancellation, and aborting a request can race with its response. A plain shared boolean lets one input release another input's recording; forgetting normal completion blocks every later recording.

**How to apply:** Stop streams returned to cancelled sessions, guard callback ownership, cancel when a target becomes read-only/disabled, preserve current text/selection and limits, and verify two consecutive dictations as well as cancellation.

**Rule:** Keep interactive speech local and isolated from GPU rendering queues; enforce inference timeouts with a killable process rather than an abandoned thread.

**Why:** Short search/chat prompts should not wait behind video work. Timing out only the HTTP await leaves a hung model holding the single-job slot indefinitely.

**How to apply:** Reuse a small CPU model in a spawned child process, terminate a timed-out child before releasing capacity, and verify the next request can recover. Describe processing as happening on the OBTV server, not on the user's device.

**Rule:** Live snapshots must be independently decodable, and only the newest pending snapshot should wait behind in-flight inference.

**Why:** MediaRecorder timeslices can contain unfinished container data, especially MP4 in Safari. Replaying every queued snapshot makes displayed speech lag progressively behind a slow model.

**How to apply:** Use complete PCM/WAV snapshots for bounded short dictation; replace the owned text range rather than appending cumulative transcripts. Prioritize the final snapshot after Stop. Abandon ownership on manual edits rather than trying to overwrite or guess how to merge them.

**Rule:** Cancel server inference on an observed client disconnect, not just a browser AbortController.

**Why:** ASGI may continue the handler after HTTP disconnect; the obsolete inference then occupies the speech slot and blocks a new dictation session.

**How to apply:** Monitor disconnects after consuming the upload, cancel and await inference before removing its temporary file, and test that the next request can acquire capacity.