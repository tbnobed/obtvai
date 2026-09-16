'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {
  apiError,
  buildResponse,
  computeAnalysis,
  responseEnvelope,
  toN8nItem,
} = require('./obtv-channel-analysis');

const exportedWorkflow = JSON.parse(
  fs.readFileSync(`${__dirname}/obtv-channel-analysis.json`, 'utf8'),
);

function exportedNode(name) {
  const node = exportedWorkflow.nodes.find((candidate) => candidate.name === name);
  assert.ok(node, `missing exported node ${name}`);
  return node;
}

function executeExportedCode(name, { json = {}, nodes = {}, startedAt = '2024-06-07T00:00:00Z' } = {}) {
  const code = exportedNode(name).parameters.jsCode;
  const nodeProxy = new Proxy(nodes, {
    get(target, property) {
      if (typeof property === 'string' && !(property in target)) {
        throw new Error(`unexecuted node accessed: ${property}`);
      }
      return target[property];
    },
  });
  const context = {
    $json: json,
    $node: nodeProxy,
    $execution: { startedAt },
    $input: {
      first: () => ({ json }),
      all: () => [{ json }],
    },
  };
  const run = vm.runInNewContext(`(function () { ${code}\n})`, context);
  return run();
}

function fullResponse(body, statusCode = 200) {
  return { body, statusCode, headers: { 'content-type': 'application/json' } };
}

const channelResponse = {
  items: [{
    id: 'UCfixture',
    snippet: {
      title: 'Fixture Channel',
      publishedAt: '2022-01-01T00:00:00Z',
    },
    statistics: {
      subscriberCount: '1200',
      viewCount: '100000',
      videoCount: '12',
    },
  }],
};

const playlistResponse = {
  items: [
    '2024-06-06',
    '2024-06-05',
    '2024-06-04',
    '2024-06-03',
    '2024-06-02',
    '2024-06-01',
  ].map((day, index) => ({
    contentDetails: {
      videoId: `video-${index + 1}`,
      videoPublishedAt: `${day}T00:00:00Z`,
    },
    snippet: {
      title: `Fixture upload ${index + 1}`,
      publishedAt: `${day}T00:00:00Z`,
    },
  })),
};

const videosResponse = {
  items: [100, 90, 80, 70, 60, 50].map((views, index) => ({
    id: `video-${index + 1}`,
    snippet: {
      title: `Fixture upload ${index + 1}`,
      publishedAt: `2024-06-0${6 - index}T00:00:00Z`,
      thumbnails: { default: { url: `https://img.example/${index + 1}.jpg` } },
    },
    statistics: {
      viewCount: String(views),
      likeCount: String(views / 10),
      commentCount: String(views / 100),
    },
  })),
};

test('computes measured metrics from at most 50 uploads and keeps an n8n item envelope', () => {
  const analysis = computeAnalysis({
    request: {
      channelId: 'UCfixture',
      history: [
        { recorded_at: '2024-05-01T00:00:00Z', followers: 1000, total_views: 80000 },
        { recorded_at: '2024-06-07T00:00:00Z', followers: 1200, total_views: 100000 },
      ],
    },
    channelResponse,
    playlistResponse,
    videosResponse,
    observedAt: '2024-06-07T00:00:00Z',
  });
  assert.equal(analysis.status, 'ready');
  assert.equal(analysis.metrics.sample_size, 6);
  assert.equal(analysis.metrics.avg_views, 75);
  assert.equal(analysis.metrics.median_views, 75);
  assert.equal(analysis.metrics.avg_likes, 7.5);
  assert.equal(analysis.metrics.avg_comments, 0.75);
  assert.equal(analysis.metrics.engagement_rate, 11);
  assert.equal(analysis.metrics.subscriber_change, 200);
  assert.equal(analysis.metrics.subscriber_change_percent, 20);
  assert.equal(analysis.metrics.history_days, 37);
  assert.equal(analysis.metrics.recent_median_views, 90);
  assert.equal(analysis.metrics.previous_median_views, 60);
  assert.equal(analysis.metrics.performance_change_percent, 50);
  assert.equal(analysis.rows.length, 6);

  const response = buildResponse(analysis, {
    choices: [{
      message: {
        content: JSON.stringify({
          summary: 'The six-upload sample averaged 75 views.',
          recommendations: ['Compare future uploads with the same sample scope.'],
        }),
      },
    }],
  });
  const item = toN8nItem(response);
  assert.deepEqual(Object.keys(item), ['json']);
  assert.equal(item.json.schemaVersion, 2);
  assert.equal(item.json.status, 'ready');
  assert.equal(item.json.topVideos[0].views, 100);
  assert.equal(item.json.aiInsights.recommendations.length, 1);
  assert.equal('profitability' in item.json, false);
  assert.equal('projections' in item.json, false);
});

test('returns a non-empty ready response with null upload metrics when there are no videos', () => {
  const analysis = computeAnalysis({
    request: { channelId: 'UCempty', history: [] },
    channelResponse: {
      items: [{
        id: 'UCempty',
        snippet: { title: 'Empty Channel' },
        statistics: { subscriberCount: '0', viewCount: '0', videoCount: '0' },
      }],
    },
    playlistResponse: { items: [] },
    videosResponse: { items: [] },
    observedAt: '2024-06-07T00:00:00Z',
  });
  const response = buildResponse(analysis, {});
  assert.equal(response.status, 'ready');
  assert.equal(response.metrics.sample_size, 0);
  assert.equal(response.metrics.avg_views, null);
  assert.equal(response.metrics.median_views, null);
  assert.deepEqual(response.topVideos, []);
  assert.ok(response.dataWarnings.some((warning) => /No public uploads/.test(warning)));
  assert.ok(response.aiInsights && Array.isArray(response.aiInsights.recommendations));
});

test('returns an explicit error object for a YouTube API failure', () => {
  const analysis = computeAnalysis({
    request: { channelId: 'UCbroken', history: [] },
    channelResponse: {
      error: { code: 403, message: 'quota exceeded' },
    },
    playlistResponse: {},
    videosResponse: {},
    observedAt: '2024-06-07T00:00:00Z',
  });
  const response = buildResponse(analysis, {});
  assert.equal(response.status, 'error');
  assert.equal(response.error.code, 'youtube_channel_failed');
  assert.match(response.error.message, /channel request failed/);
  assert.ok(response.metrics && typeof response.metrics === 'object');
  assert.ok(Array.isArray(response.dataWarnings));
  assert.ok(Array.isArray(response.topVideos));
  assert.equal(response.aiInsights.summary, null);
});

test('keeps measured metrics usable when OpenAI returns an error or malformed JSON', () => {
  const analysis = computeAnalysis({
    request: { channelId: 'UCfixture', history: [] },
    channelResponse,
    playlistResponse: { items: playlistResponse.items.slice(0, 1) },
    videosResponse: { items: videosResponse.items.slice(0, 1) },
    observedAt: '2024-06-07T00:00:00Z',
  });
  const response = buildResponse(analysis, {
    error: { message: 'temporary upstream failure' },
  });
  assert.equal(response.status, 'ready');
  assert.equal(response.metrics.sample_size, 1);
  assert.equal(response.aiInsights.summary, null);
  assert.deepEqual(response.aiInsights.recommendations, []);
  assert.ok(response.dataWarnings.some((warning) => /OpenAI strategy output/.test(warning)));
});

test('preserves full HTTP bodies/statuses, rejects malformed responses, and accepts real empty lists', () => {
  const nested429 = fullResponse({
    error: { code: 429, message: 'quota exceeded' },
  }, 429);
  assert.deepEqual(responseEnvelope(nested429), {
    body: { error: { code: 429, message: 'quota exceeded' } },
    statusCode: 429,
  });
  assert.equal(apiError(nested429, 'channel').code, 'youtube_channel_rate_limited');
  assert.equal(apiError(nested429, 'channel').httpStatus, 429);
  const nested429WithSuccessfulTransport = fullResponse({
    error: { code: 429, message: 'quota exceeded' },
  }, 200);
  assert.equal(apiError(nested429WithSuccessfulTransport, 'channel').httpStatus, 429);
  assert.equal(apiError(fullResponse({}, 200), 'uploads').code, 'youtube_uploads_malformed');
  assert.equal(apiError(fullResponse({ items: [] }, 200), 'uploads'), null);
  assert.equal(apiError(fullResponse({ items: [] }, 200), 'video_stats'), null);
});

function runExportedPipeline({
  channel = channelResponse,
  playlist = playlistResponse,
  videos = videosResponse,
  aiContent = JSON.stringify({
    summary: 'The measured sample averaged 75 views.',
    recommendations: ['Keep the sample scope explicit.'],
  }),
  includeVideoNode = true,
  channelStatus = 200,
} = {}) {
  const normalized = executeExportedCode('Normalize Request', {
    json: { body: { channelId: channel.items?.[0]?.id || 'UCfixture', history: [] } },
  });
  const normalizedNode = { json: normalized[0].json };
  const prepared = executeExportedCode('Prepare Video IDs', {
    json: fullResponse(playlist),
  });
  const channelNode = { json: fullResponse(channel, channelStatus) };
  const playlistNode = { json: fullResponse(playlist) };
  const normalizedVideo = executeExportedCode('YouTube: Get Video Stats', {
    json: includeVideoNode ? fullResponse(videos) : prepared[0].json,
  });
  const nodes = {
    'Normalize Request': normalizedNode,
    'YouTube: Get Channel Info': channelNode,
    'YouTube: List Uploads': playlistNode,
    'YouTube: Get Video Stats': { json: normalizedVideo[0].json },
  };
  const computed = executeExportedCode('Compute Metrics', {
    nodes,
  });
  const computedNode = { json: computed[0].json };
  executeExportedCode('Build OpenAI Strategy Request', {
    nodes: { 'Compute Metrics': computedNode },
  });
  const assembled = executeExportedCode('Assemble Response', {
    nodes: {
      'Compute Metrics': computedNode,
      'OpenAI: Strategy JSON': {
        json: fullResponse({
          choices: [{ message: { content: aiContent } }],
        }),
      },
    },
  });
  return { prepared: prepared[0].json, computed: computed[0].json, response: assembled[0].json };
}

test('executes the exported Code nodes for success, fenced AI, and empty playlist paths', () => {
  const success = runExportedPipeline({
    aiContent: '```json\n{"summary":"Grounded summary.","recommendations":["Use measured sample."]}\n```',
  });
  assert.equal(success.prepared.videoIds, 'video-1,video-2,video-3,video-4,video-5,video-6');
  assert.equal(success.computed.analysis.status, 'ready');
  assert.equal(success.response.status, 'ready');
  assert.equal(success.response.aiInsights.summary, 'Grounded summary.');
  assert.deepEqual(Array.from(success.response.aiInsights.recommendations), ['Use measured sample.']);

  const empty = runExportedPipeline({
    playlist: { items: [] },
    videos: { items: [] },
    includeVideoNode: false,
    aiContent: '```json\n{"summary":"No uploads were returned.","recommendations":[]}\n```',
  });
  assert.equal(empty.prepared.videoIds, '');
  assert.equal(empty.computed.analysis.status, 'ready');
  assert.equal(empty.response.metrics.subscriber_count, 1200);
  assert.equal(empty.response.metrics.total_views, 100000);
  assert.equal(empty.response.metrics.sample_size, 0);
  assert.equal(empty.response.metrics.avg_views, null);
  assert.deepEqual(empty.response.topVideos, []);
});

test('executes the exported Code nodes for nested YouTube 429 and retains structured error output', () => {
  const error = runExportedPipeline({
    channel: { error: { code: 429, message: 'quota exceeded' } },
    playlist: { items: [] },
    videos: { items: [] },
    includeVideoNode: false,
    channelStatus: 200,
  });
  assert.equal(error.computed.analysis.status, 'error');
  assert.equal(error.computed.analysis.error.code, 'youtube_channel_rate_limited');
  assert.equal(error.response.status, 'error');
  assert.equal(error.response.error.code, 'youtube_channel_rate_limited');
  assert.equal(error.response.error.message, 'YouTube upstream request failed (HTTP 429).');
  assert.equal(error.response.metrics.sample_size, 0);
});

test('exports full-response JSON HTTP options and a conditional zero-ID branch', () => {
  const httpNodes = exportedWorkflow.nodes.filter(
    (node) => node.type === 'n8n-nodes-base.httpRequest',
  );
  assert.equal(httpNodes.length, 4);
  for (const node of httpNodes) {
    const responseOptions = node.parameters.options.response.response;
    assert.equal(responseOptions.fullResponse, true, node.name);
    assert.equal(responseOptions.neverError, true, node.name);
    assert.equal(responseOptions.responseFormat, 'json', node.name);
  }
  const videoHttpNode = exportedNode('YouTube: Get Video Stats HTTP');
  assert.match(
    videoHttpNode.parameters.queryParameters.parameters
      .find((parameter) => parameter.name === 'id').value,
    /Prepare Video IDs/,
  );
  const listConnections = exportedWorkflow.connections['YouTube: List Uploads'].main[0];
  assert.deepEqual(listConnections.map((connection) => connection.node), ['Prepare Video IDs']);
  const branch = exportedWorkflow.connections['Has Video IDs'].main;
  assert.deepEqual(branch[0].map((connection) => connection.node), ['YouTube: Get Video Stats HTTP']);
  assert.deepEqual(branch[1].map((connection) => connection.node), ['YouTube: Get Video Stats']);
  const responseCode = exportedNode('Respond Error').parameters.options.responseCode;
  assert.match(responseCode, /rate_limited.*429/);
  assert.match(responseCode, /youtube_channel_not_found.*400/);
  assert.match(responseCode, /startsWith\('youtube_'\).*502/);
});