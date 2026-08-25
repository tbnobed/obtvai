---
name: BAGEL caption timeout behavior
description: How a slow or stuck BAGEL image inference turns into a misleading long-running caption batch.
---

BAGEL's health endpoint only proves that the model loaded. It does not prove that an image inference can finish. The service serializes inference with a process lock; when a caller times out while the first forward pass remains inside that lock, later requests queue behind it and time out too.

**Why:** A caption batch appeared to run for hours while every `/caption` request timed out at the client deadline. The worker kept moving to the next scene, but the server's original inference still held the lock.

**How to apply:** Cancel the batch and restart the BAGEL service to clear the held inference. Run one image smoke test and inspect server-side start/finish timing before queueing a full scene batch. Caption workers should update progress by attempted frames and fail after a short run of consecutive inference failures rather than silently spending hours on timeouts. On the current co-resident Spark setup, successful 32-token requests have ranged from roughly 80–180 seconds in a batch, so a few hundred scenes can take most of a day even after the timeout problem is fixed.