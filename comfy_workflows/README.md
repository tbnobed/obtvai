# Custom ComfyUI workflows

Drop ComfyUI workflow JSON files here and they show up as extra presets on the
Graphics page (marked "custom").

How to export one:

1. Build and test the workflow in the ComfyUI UI until it generates what you want.
2. Use **Workflow → Export (API)** — the file must be the *API format*
   (`{"1": {"class_type": ..., "inputs": ...}, ...}`), not the regular save format.
3. Copy the `.json` file into this folder. No restart needed — presets are
   rescanned on every request.

What gets injected automatically at generation time:

- The prompt goes into the `CLIPTextEncode` node titled **prompt** (or
  "positive"). Title a second one **negative** to receive the negative prompt.
- Any `seed` / `noise_seed` input gets the seed.
- Nodes with `width` + `height` inputs get the requested size.
- `length` / `frames` / `num_frames` inputs get the requested frame count.
- `steps` inputs get the requested step count.

Outputs: end the workflow in `SaveImage`. A single saved image becomes an image
result; a saved PNG sequence is assembled into an MP4 automatically. Native
video-save nodes (e.g. VHS) also work — the video file is picked up directly.
