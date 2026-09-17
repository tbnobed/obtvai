import assert from 'node:assert/strict';
import test from 'node:test';
import {
  DICTATION_MAX_PCM_SAMPLES,
  DICTATION_SAMPLE_RATE,
  encodePcm16Wav,
} from './audio-capture.ts';

test('encodePcm16Wav emits bounded mono 16 kHz PCM WAV', async () => {
  const wav = encodePcm16Wav(new Float32Array([0, 1, -1, 0.5]));
  const bytes = new Uint8Array(await wav.arrayBuffer());
  const view = new DataView(bytes.buffer);

  assert.equal(wav.type, 'audio/wav');
  assert.equal(String.fromCharCode(...bytes.subarray(0, 4)), 'RIFF');
  assert.equal(String.fromCharCode(...bytes.subarray(8, 12)), 'WAVE');
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), DICTATION_SAMPLE_RATE);
  assert.equal(view.getUint32(40, true), 8);
  assert.equal(wav.size, 52);
});

test('encodePcm16Wav clamps snapshots to the 60 second PCM budget', () => {
  const wav = encodePcm16Wav(new Float32Array(DICTATION_MAX_PCM_SAMPLES + 1));
  assert.equal(wav.size, 44 + DICTATION_MAX_PCM_SAMPLES * 2);
});
