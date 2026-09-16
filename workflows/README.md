# OBTV channel analysis workflow

`obtv-channel-analysis.json` is a credential-free n8n export for the existing
`POST /webhook/analyze-channel` endpoint. It samples the channel's uploads
playlist (at most 50 items), then batches `videos.list` for lifetime-to-date
view/like/comment counts. It does not use `search.list`, and it contains no
MCN economics, revenue assumptions, risk scores, or subscriber projections.

## Import and bind credentials

1. Import `obtv-channel-analysis.json` into n8n without changing the webhook
   path (`analyze-channel`) or the response mode (`Using Respond to Webhook
   Node`).
2. On each `YouTube: ...` HTTP Request node, select the existing credential
   whose type is **Query Auth** (`httpQueryAuth`). Configure its query
   parameter name as `key` and its value as the YouTube Data API key. The
   export contains only the credential type/name reference; it does not
   contain a key.
3. On `OpenAI: Strategy JSON`, select the existing **Header Auth**
   (`httpHeaderAuth`) credential. Configure the header name as `Authorization`
   and the value as `Bearer <the OpenAI API key>`. Do not paste a key into the
   workflow JSON.
4. Activate the workflow after selecting both credentials. n8n may show the
   credential references as needing selection when an imported credential name
   differs between instances.
   Only one active workflow may own `analyze-channel`; deactivate or remove an
   older workflow with the same webhook path before activating this export to
   avoid webhook activation conflicts.

The export uses current n8n node shapes (`Webhook` 2.1, `HTTP Request` 4.2,
`Code` 2, `IF` 2.2, and `Respond to Webhook` 1.4). If an older n8n build
renders an HTTP Request node differently, keep the same URL, query names,
`neverError`/continue-on-fail behaviour, and credential type when rebinding.

## Request and response

Send a JSON object with a channel ID. `history` is optional and should contain
OBTV's stored snapshots when available:

```json
{
  "channelId": "UCxxxxxxxxxxxxxxxxxxxxxx",
  "history": [
    { "recorded_at": "2024-01-01T00:00:00Z", "followers": 1000, "total_views": 50000 },
    { "recorded_at": "2024-02-01T00:00:00Z", "followers": 1100, "total_views": 70000 }
  ]
}
```

Every execution returns one JSON object with `schemaVersion: 2` and either
`status: "ready"` or `status: "error"`. A ready response contains nullable
measured `metrics`, `dataWarnings`, structured `aiInsights`, and `topVideos`.
The top-video list is ranked only within the sampled recent uploads. Video
counts are lifetime-to-date observations, not monthly channel views.

The YouTube and OpenAI HTTP nodes retain a JSON body plus HTTP status and use
`neverError` so non-2xx JSON error bodies remain available to the computation.
The video-stats request is behind a video-ID check: an empty uploads playlist
does not send `videos.list?id=` and still returns the real channel counts with
`sample_size: 0` and null upload metrics. Upstream rate limits map to HTTP 429,
other upstream/malformed responses to 502, and malformed requests/channel
absence to 400 while retaining the structured v2 response body.

Missing measurements are `null`, not zero. `subscriber_change` is populated
only from at least two dated OBTV snapshots. Cadence and the optional
recent/previous comparison include their coverage limitations in
`dataWarnings`. If OpenAI fails or returns non-JSON, the workflow still
returns measured metrics with a warning and empty/null `aiInsights`.
YouTube/API failures and malformed requests return a non-empty error object;
an empty uploads playlist is a valid ready response with null upload metrics.

## Offline checks

The pure computation and the exported n8n Code nodes are covered without live
network calls. Run:

```sh
node --test workflows/obtv-channel-analysis.test.js
```

These fixtures execute the exported Code-node JavaScript with mocked n8n
`$input`/`$node` values, and cover the n8n item envelope, measured
calculations, empty uploads, malformed/full-response HTTP bodies, nested
429s, fenced OpenAI JSON, the conditional no-video branch, and OpenAI
failure. They do not make live YouTube, OpenAI, or n8n requests and therefore
are not a claim of live n8n verification.