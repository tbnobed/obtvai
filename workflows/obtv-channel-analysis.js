'use strict';

/**
 * Pure computation helpers for workflows/obtv-channel-analysis.json.
 *
 * The n8n export contains an inline copy of the small runtime-safe portion of
 * this module because n8n Code nodes cannot import files from an export.  Keep
 * the behaviour here in sync with the inline Compute Metrics and Assemble
 * Response nodes.  This module is intentionally dependency-free so it can be
 * exercised offline with node --test.
 */

const DAY_MS = 24 * 60 * 60 * 1000;
const MAX_UPLOADS = 50;

const METRIC_KEYS = [
  'subscriber_count',
  'total_views',
  'total_videos',
  'sample_size',
  'avg_views',
  'median_views',
  'avg_likes',
  'avg_comments',
  'engagement_rate',
  'uploads_last_30d',
  'uploads_per_week',
  'recent_median_views',
  'previous_median_views',
  'performance_change_percent',
  'subscriber_change',
  'subscriber_change_percent',
  'history_days',
  'observed_at',
  'sample_oldest_at',
  'sample_newest_at',
];

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

function round(value, places = 2) {
  if (!Number.isFinite(value)) return null;
  const factor = 10 ** places;
  return Math.round(value * factor) / factor;
}

function isoDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function median(values) {
  const numbers = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!numbers.length) return null;
  const middle = Math.floor(numbers.length / 2);
  return numbers.length % 2
    ? numbers[middle]
    : (numbers[middle - 1] + numbers[middle]) / 2;
}

function uniqueWarnings(warnings) {
  return [...new Set(warnings.filter((warning) => typeof warning === 'string' && warning.trim()))];
}

function firstItem(value) {
  return Array.isArray(value) ? (value[0] || null) : value;
}

function parseResponseBody(value) {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch (_error) {
    return null;
  }
}

/**
 * HTTP Request nodes are configured with fullResponse. Keep body and status
 * together while still accepting direct JSON fixtures in offline tests.
 */
function responseEnvelope(value) {
  const raw = firstItem(value);
  if (!raw || typeof raw !== 'object') return { body: null, statusCode: null };
  const isFullResponse =
    Object.prototype.hasOwnProperty.call(raw, 'body') &&
    (Object.prototype.hasOwnProperty.call(raw, 'statusCode') ||
      Object.prototype.hasOwnProperty.call(raw, 'status') ||
      Object.prototype.hasOwnProperty.call(raw, 'headers'));
  if (isFullResponse) {
    return {
      body: parseResponseBody(raw.body),
      statusCode: Number(raw.statusCode || raw.status) || null,
    };
  }
  return {
    body: raw,
    statusCode: Number(raw.statusCode || raw.status) || null,
  };
}

function unwrap(value) {
  return responseEnvelope(value).body;
}

function apiError(response, label) {
  const envelope = responseEnvelope(response);
  const body = envelope.body;
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return {
      code: `youtube_${label}_empty`,
      message: `YouTube ${label} response was empty.`,
      httpStatus: 502,
    };
  }

  const nestedError = body.error && typeof body.error === 'object' ? body.error : null;
  const nestedCode = nestedError && nestedError.code;
  const nestedStatus = nestedError && (nestedError.statusCode || nestedError.status);
  const statusCandidate =
    nestedStatus ||
    nestedCode ||
    envelope.statusCode ||
    body.statusCode ||
    body.status ||
    body.code;
  const status = Number(statusCandidate);
  const mappedStatus = status === 429 ? 429 : status >= 500 ? 502 : 502;

  if (body.error || body.__n8nError || (body.code && body.message && !Array.isArray(body.items))) {
    return {
      code: status === 429 || Number(nestedCode) === 429
        ? `youtube_${label}_rate_limited`
        : `youtube_${label}_failed`,
      message: `YouTube ${label} request failed${status ? ` (HTTP ${status})` : ''}.`,
      httpStatus: mappedStatus,
    };
  }

  // A real empty list is valid. An empty/malformed object is not a valid
  // YouTube response and must not be mistaken for an empty channel.
  if (!Array.isArray(body.items)) {
    return {
      code: `youtube_${label}_malformed`,
      message: `YouTube ${label} response did not contain an items array.`,
      httpStatus: 502,
    };
  }
  return null;
}

function normalizeHistory(history) {
  if (!Array.isArray(history)) return [];
  return history
    .map((record) => ({
      recorded_at: isoDate(record && record.recorded_at),
      followers: numberOrNull(record && record.followers),
      total_views: numberOrNull(record && record.total_views),
    }))
    .filter((record) => record.recorded_at && record.followers !== null)
    .sort((a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime());
}

function buildVideoRows(playlistResponse, videosResponse) {
  const playlist = unwrap(playlistResponse);
  const details = unwrap(videosResponse);
  const detailById = new Map(
    (Array.isArray(details.items) ? details.items : [])
      .filter((video) => video && video.id)
      .map((video) => [video.id, video]),
  );
  const seen = new Set();
  const uploads = Array.isArray(playlist.items) ? playlist.items : [];

  return uploads
    .map((upload) => {
      const id = upload && upload.contentDetails && upload.contentDetails.videoId;
      if (!id || seen.has(id)) return null;
      seen.add(id);
      const detail = detailById.get(id) || {};
      const playlistSnippet = upload.snippet || {};
      const snippet = detail.snippet || {};
      const stats = detail.statistics || {};
      return {
        id: String(id),
        title: String(snippet.title || playlistSnippet.title || ''),
        views: numberOrNull(stats.viewCount),
        likes: numberOrNull(stats.likeCount),
        comments: numberOrNull(stats.commentCount),
        published_at: isoDate(
          snippet.publishedAt ||
            upload.contentDetails.videoPublishedAt ||
            playlistSnippet.publishedAt,
        ),
        thumbnail_url:
          (snippet.thumbnails && (snippet.thumbnails.high || snippet.thumbnails.medium || snippet.thumbnails.default)?.url) ||
          (playlistSnippet.thumbnails &&
            (playlistSnippet.thumbnails.high ||
              playlistSnippet.thumbnails.medium ||
              playlistSnippet.thumbnails.default)?.url) ||
          null,
      };
    })
    .filter(Boolean)
    .slice(0, MAX_UPLOADS);
}

function emptyMetrics(observedAt = null) {
  const metrics = {};
  for (const key of METRIC_KEYS) metrics[key] = null;
  metrics.observed_at = isoDate(observedAt) || null;
  return metrics;
}

function computeMetrics({ channelResponse, playlistResponse, videosResponse, history = [], observedAt }) {
  const channelBody = unwrap(channelResponse);
  const channel = (Array.isArray(channelBody.items) && channelBody.items[0]) || {};
  const statistics = channel.statistics || {};
  const rows = buildVideoRows(playlistResponse, videosResponse);
  const observed = isoDate(observedAt) || new Date().toISOString();
  const metrics = emptyMetrics(observed);
  const warnings = [
    'Sample is limited to the 50 most recent uploads returned by the uploads playlist.',
    'Video views, likes, and comments are lifetime-to-date counts for sampled videos; they are not monthly channel views.',
    'Public YouTube data does not provide CTR, retention, watch time, revenue, or causal explanations.',
  ];

  metrics.subscriber_count = numberOrNull(statistics.subscriberCount);
  metrics.total_views = numberOrNull(statistics.viewCount);
  metrics.total_videos = numberOrNull(statistics.videoCount);
  metrics.sample_size = rows.length;

  const views = rows.map((row) => row.views).filter((value) => value !== null);
  const likes = rows.map((row) => row.likes).filter((value) => value !== null);
  const comments = rows.map((row) => row.comments).filter((value) => value !== null);
  metrics.avg_views = views.length ? round(views.reduce((sum, value) => sum + value, 0) / views.length) : null;
  metrics.median_views = median(views);
  metrics.avg_likes = likes.length ? round(likes.reduce((sum, value) => sum + value, 0) / likes.length) : null;
  metrics.avg_comments = comments.length
    ? round(comments.reduce((sum, value) => sum + value, 0) / comments.length)
    : null;

  if (rows.length && (likes.length < rows.length || comments.length < rows.length)) {
    warnings.push('Likes and/or comments are partial for the sampled uploads; engagement_rate is unavailable.');
  }
  if (rows.length && views.length < rows.length) {
    warnings.push('Views are partial for the sampled uploads; view aggregates and engagement_rate may be unavailable.');
  }
  const completeEngagement = rows.filter(
    (row) => row.views !== null && row.likes !== null && row.comments !== null,
  );
  const engagementViews = completeEngagement.reduce((sum, row) => sum + row.views, 0);
  const engagementActions = completeEngagement.reduce(
    (sum, row) => sum + row.likes + row.comments,
    0,
  );
  metrics.engagement_rate =
    completeEngagement.length === rows.length && engagementViews > 0
      ? round((engagementActions / engagementViews) * 100)
      : null;

  const datedRows = rows
    .filter((row) => row.published_at)
    .sort((a, b) => new Date(a.published_at).getTime() - new Date(b.published_at).getTime());
  if (datedRows.length) {
    metrics.sample_oldest_at = datedRows[0].published_at;
    metrics.sample_newest_at = datedRows[datedRows.length - 1].published_at;
    const observedTime = new Date(observed).getTime();
    const cutoff = observedTime - 30 * DAY_MS;
    metrics.uploads_last_30d = datedRows.filter(
      (row) => new Date(row.published_at).getTime() >= cutoff && new Date(row.published_at).getTime() <= observedTime,
    ).length;
    if (datedRows.length > 1) {
      const coverageDays =
        (new Date(metrics.sample_newest_at).getTime() - new Date(metrics.sample_oldest_at).getTime()) / DAY_MS;
      if (coverageDays > 0) metrics.uploads_per_week = round(datedRows.length / (coverageDays / 7));
    }
    if (new Date(metrics.sample_oldest_at).getTime() > cutoff) {
      warnings.push('The sampled publication dates do not cover a full 30-day window; uploads_last_30d may be incomplete.');
    }
  } else if (rows.length) {
    warnings.push('Sample publication dates are missing; cadence and date coverage remain unavailable.');
  }

  const comparisonRows = rows
    .filter((row) => row.published_at && row.views !== null)
    .sort((a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime());
  if (comparisonRows.length >= 6) {
    const recentCount = Math.ceil(comparisonRows.length / 2);
    const recent = comparisonRows.slice(0, recentCount).map((row) => row.views);
    const previous = comparisonRows.slice(recentCount).map((row) => row.views);
    if (recent.length >= 3 && previous.length >= 3) {
      metrics.recent_median_views = median(recent);
      metrics.previous_median_views = median(previous);
      if (metrics.previous_median_views > 0) {
        metrics.performance_change_percent = round(
          ((metrics.recent_median_views - metrics.previous_median_views) /
            metrics.previous_median_views) *
            100,
        );
      } else {
        warnings.push('The older comparison median is zero; performance_change_percent is unavailable.');
      }
      warnings.push(
        'The recent/previous comparison is an age-biased observed comparison of lifetime sample counts, not view velocity or causal growth.',
      );
    }
  } else if (rows.length) {
    warnings.push('At least six dated uploads with views are needed for the observed recent/previous comparison.');
  }

  const normalizedHistory = normalizeHistory(history);
  if (normalizedHistory.length >= 2) {
    const first = normalizedHistory[0];
    const last = normalizedHistory[normalizedHistory.length - 1];
    const historyDays = (new Date(last.recorded_at).getTime() - new Date(first.recorded_at).getTime()) / DAY_MS;
    if (historyDays > 0) {
      metrics.history_days = round(historyDays);
      metrics.subscriber_change = last.followers - first.followers;
      metrics.subscriber_change_percent =
        first.followers > 0 ? round((metrics.subscriber_change / first.followers) * 100) : null;
    } else {
      warnings.push('OBTV history snapshots need distinct dates; subscriber change is unavailable.');
    }
  } else {
    warnings.push('OBTV history has fewer than two dated snapshots; subscriber change is unavailable.');
  }

  if (!rows.length) {
    warnings.push('No public uploads were returned; upload-level metrics remain null.');
  }
  return { metrics, rows, warnings: uniqueWarnings(warnings) };
}

function computeAnalysis({
  request = {},
  channelResponse,
  playlistResponse,
  videosResponse,
  observedAt,
}) {
  const channelError = apiError(channelResponse, 'channel');
  const playlistError = apiError(playlistResponse, 'uploads');
  const playlistBody = unwrap(playlistResponse);
  const hasUploads = Array.isArray(playlistBody.items) && playlistBody.items.length > 0;
  // An empty uploads playlist intentionally results in an empty video-stats
  // request. Do not turn that expected no-data case into an API error.
  const videosError = hasUploads ? apiError(videosResponse, 'video_stats') : null;
  const channelBody = unwrap(channelResponse);
  const channel = (Array.isArray(channelBody.items) && channelBody.items[0]) || {};
  const base = computeMetrics({
    channelResponse,
    playlistResponse,
    videosResponse,
    history: request.history,
    observedAt,
  });
  const requestError = request.channelId
    ? null
    : { code: 'invalid_request', message: 'channelId is required.' };
  let error = requestError || channelError || playlistError || videosError;
  if (!error && !channel.id) {
    error = {
      code: 'youtube_channel_not_found',
      message: 'YouTube did not return a channel for the supplied channelId.',
    };
  }
  return {
    status: error ? 'error' : 'ready',
    error: error || null,
    channel: {
      id: channel.id || request.channelId || null,
      title: (channel.snippet && channel.snippet.title) || null,
      published_at: isoDate(channel.snippet && channel.snippet.publishedAt),
    },
    metrics: base.metrics,
    rows: base.rows,
    warnings: base.warnings,
  };
}

function parseAiResponse(response) {
  const body = unwrap(response);
  if (body && body.error) {
    return { value: { summary: null, recommendations: [] }, failed: true };
  }
  const content = body && body.choices && body.choices[0] && body.choices[0].message
    ? body.choices[0].message.content
    : null;
  if (!content) return { value: { summary: null, recommendations: [] }, failed: true };
  let parsed = content;
  if (typeof content === 'string') {
    try {
      parsed = JSON.parse(content.replace(/^```(?:json)?\s*|\s*```$/g, '').trim());
    } catch (_error) {
      return { value: { summary: null, recommendations: [] }, failed: true };
    }
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { value: { summary: null, recommendations: [] }, failed: true };
  }
  const summary = typeof parsed.summary === 'string' && parsed.summary.trim() ? parsed.summary.trim() : null;
  const recommendations = Array.isArray(parsed.recommendations)
    ? parsed.recommendations.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim())
    : [];
  if (!summary && !recommendations.length) {
    return { value: { summary: null, recommendations: [] }, failed: true };
  }
  return { value: { summary, recommendations }, failed: false };
}

function buildResponse(analysis, aiResponse) {
  const ai = parseAiResponse(aiResponse);
  const warnings = [...analysis.warnings];
  if (ai.failed && analysis.status === 'ready') {
    warnings.push('OpenAI strategy output was unavailable or not valid JSON; measured metrics remain usable.');
  }
  const response = {
    schemaVersion: 2,
    status: analysis.status,
    channel: analysis.channel,
    metrics: analysis.metrics,
    dataWarnings: uniqueWarnings(warnings),
    aiInsights: analysis.status === 'ready' ? ai.value : { summary: null, recommendations: [] },
    topVideos: analysis.rows
      .slice()
      .sort((a, b) => (b.views === null ? -1 : a.views === null ? 1 : b.views - a.views))
      .slice(0, 5),
  };
  if (analysis.error) {
    const { httpStatus: _httpStatus, ...publicError } = analysis.error;
    response.error = publicError;
  }
  return response;
}

function toN8nItem(value) {
  return { json: value };
}

module.exports = {
  MAX_UPLOADS,
  METRIC_KEYS,
  buildResponse,
  buildVideoRows,
  apiError,
  computeAnalysis,
  computeMetrics,
  isoDate,
  median,
  normalizeHistory,
  numberOrNull,
  parseAiResponse,
  responseEnvelope,
  toN8nItem,
  unwrap,
};