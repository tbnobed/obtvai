---
name: Async subprocess cleanup and capacity
description: Killed children can still retain asyncio pipe waiters and leak capacity reservations.
---

Killing an asyncio subprocess does not guarantee that awaiting its exit completes when its stdout pipe is paused and unread. Cleanup must discard remaining output in bounded chunks, bound the wait, withstand repeated cancellation, and unconditionally release capacity.

**Why:** Playback returned persistent capacity errors with no living ffmpeg processes. Real subprocess tests reproduced two killed children leaving both playback slots occupied because their pipe transports never finished.

**How to apply:** Test output-limit, timeout, disconnect, and repeated-cancellation paths using real children that fill stdout beyond its high-water mark. Verify subsequent requests can acquire every slot; checking that the child exited is insufficient.