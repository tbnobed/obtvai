/**
 * Small, deliberately dependency-free PCM capture primitive for dictation.
 *
 * MediaRecorder is not used here: browsers commonly leave the last WebM/Opus
 * cluster unfinished when stop() is called, which makes a live snapshot
 * unusable.  This helper keeps bounded mono PCM and emits self-contained WAV
 * snapshots instead.
 */

export const DICTATION_SAMPLE_RATE = 16_000;
export const DICTATION_MAX_SECONDS = 60;
export const DICTATION_MAX_PCM_SAMPLES =
  DICTATION_SAMPLE_RATE * DICTATION_MAX_SECONDS;
export const DICTATION_MAX_REQUEST_BYTES = 8 * 1024 * 1024;

const WORKLET_SOURCE = `
class DictationCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (input && input.length) {
      this.port.postMessage(input.slice(0));
    }
    return true;
  }
}
registerProcessor('dictation-capture', DictationCaptureProcessor);
`;

export function encodePcm16Wav(
  samples: Float32Array | readonly number[],
  sampleRate = DICTATION_SAMPLE_RATE,
): Blob {
  const count = Math.min(samples.length, DICTATION_MAX_PCM_SAMPLES);
  const buffer = new ArrayBuffer(44 + count * 2);
  const view = new DataView(buffer);
  const write = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i += 1) {
      view.setUint8(offset + i, value.charCodeAt(i));
    }
  };
  write(0, 'RIFF');
  view.setUint32(4, 36 + count * 2, true);
  write(8, 'WAVE');
  write(12, 'fmt ');
  view.setUint32(16, 16, true); // PCM format chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, 'data');
  view.setUint32(40, count * 2, true);
  for (let i = 0; i < count; i += 1) {
    const sample = Math.max(-1, Math.min(1, Number(samples[i]) || 0));
    view.setInt16(
      44 + i * 2,
      sample < 0 ? Math.round(sample * 0x8000) : Math.round(sample * 0x7fff),
      true,
    );
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

export interface AudioCapture {
  /** Call as soon as a user gesture starts, before awaiting permission. */
  prepare(): void;
  start(stream: MediaStream): Promise<void>;
  snapshot(): Blob | null;
  hasSpeechSince(sampleOffset: number): boolean;
  get sampleCount(): number;
  dispose(): void;
}

export interface AudioCaptureOptions {
  onError?: (error: unknown) => void;
}

function contextConstructor(): typeof AudioContext | null {
  if (typeof window === 'undefined') return null;
  return (
    window.AudioContext ||
    (window as typeof window & { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext ||
    null
  );
}

/**
 * Capture mono microphone PCM. AudioWorklet is attempted first; the legacy
 * ScriptProcessor path is only selected when worklet module startup rejects
 * explicitly (older Safari/WebViews).
 */
export function createAudioCapture(
  options: AudioCaptureOptions = {},
): AudioCapture {
  let context: AudioContext | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let processor: AudioWorkletNode | ScriptProcessorNode | null = null;
  let sink: GainNode | null = null;
  let workletUrl: string | null = null;
  let samples = new Float32Array(DICTATION_MAX_PCM_SAMPLES);
  let sampleCount = 0;
  let speechSampleCount = 0;
  let disposed = false;
  let inputSampleRate = DICTATION_SAMPLE_RATE;

  const append = (input: Float32Array, sampleRate: number) => {
    if (disposed || sampleCount >= DICTATION_MAX_PCM_SAMPLES) return;
    // Linear interpolation per render quantum keeps memory bounded at exactly
    // 60 seconds of 16 kHz mono, regardless of the device rate.
    const ratio = DICTATION_SAMPLE_RATE / (sampleRate || DICTATION_SAMPLE_RATE);
    const outputLength = Math.max(1, Math.floor(input.length * ratio));
    let energy = 0;
    for (let i = 0; i < outputLength; i += 1) {
      const position = i / ratio;
      const left = Math.min(input.length - 1, Math.floor(position));
      const right = Math.min(input.length - 1, left + 1);
      const amount = position - left;
      const value = input[left] * (1 - amount) + input[right] * amount;
      if (sampleCount < samples.length) {
        samples[sampleCount] = value;
        sampleCount += 1;
      }
      energy += value * value;
    }
    if (outputLength > 0 && Math.sqrt(energy / outputLength) >= 0.008) {
      speechSampleCount = sampleCount;
    }
  };

  const handleError = (error: unknown) => {
    if (disposed) return;
    options.onError?.(error);
  };

  const disconnect = () => {
    if (processor) {
      processor.disconnect();
      if (
        typeof AudioWorkletNode !== 'undefined' &&
        processor instanceof AudioWorkletNode
      ) {
        processor.port.onmessage = null;
      }
      processor = null;
    }
    source?.disconnect();
    source = null;
    sink?.disconnect();
    sink = null;
    if (workletUrl) {
      URL.revokeObjectURL(workletUrl);
      workletUrl = null;
    }
  };

  const prepare = () => {
    if (context || disposed) return;
    const Constructor = contextConstructor();
    if (!Constructor) return;
    try {
      context = new Constructor();
      // Do not await this call: issuing resume in the synchronous gesture
      // handler is important on Safari. start() awaits it again below.
      void context.resume().catch(() => undefined);
    } catch (error) {
      const failedContext = context;
      context = null;
      if (failedContext) void failedContext.close().catch(() => undefined);
      throw error;
    }
  };

  const start = async (stream: MediaStream) => {
    if (disposed) throw new Error('Audio capture has been disposed.');
    prepare();
    if (!context) throw new Error('Audio capture is not supported in this browser.');
    await context.resume();
    if (disposed) throw new Error('Audio capture has been disposed.');
    inputSampleRate = context.sampleRate || DICTATION_SAMPLE_RATE;
    context.onstatechange = () => {
      if (context?.state === 'suspended') {
        void context.resume().catch(handleError);
      } else if (context?.state === 'closed') {
        handleError(new Error('Audio context ended unexpectedly.'));
      }
    };
    stream.getTracks().forEach((track) => {
      track.addEventListener('ended', () => {
        if (!disposed && track.readyState === 'ended') {
          handleError(new Error('Microphone track ended unexpectedly.'));
        }
      });
    });
    source = context.createMediaStreamSource(stream);
    sink = context.createGain();
    sink.gain.value = 0;

    // A failed worklet module load is an explicit fallback condition. Other
    // capture errors are reported and allowed to reject startup.
    let workletStarted = false;
    if (context.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
      workletUrl = URL.createObjectURL(
        new Blob([WORKLET_SOURCE], { type: 'application/javascript' }),
      );
      try {
        await context.audioWorklet.addModule(workletUrl);
        const node = new AudioWorkletNode(context, 'dictation-capture');
        node.port.onmessage = (event: MessageEvent<Float32Array>) => {
          if (event.data instanceof Float32Array) {
            append(event.data, inputSampleRate);
          }
        };
        node.onprocessorerror = (event) => handleError(event);
        processor = node;
        workletStarted = true;
      } catch (error) {
        // Worklet startup can fail in Safari and embedded WebViews. Revoke
        // the failed module before using the supported fallback.
        if (workletUrl) URL.revokeObjectURL(workletUrl);
        workletUrl = null;
      }
    }

    if (!workletStarted) {
      if (typeof context.createScriptProcessor !== 'function') {
        disconnect();
        throw new Error('AudioWorklet and ScriptProcessor are unavailable.');
      }
      const node = context.createScriptProcessor(4096, 1, 1);
      node.onaudioprocess = (event) => {
        append(event.inputBuffer.getChannelData(0), inputSampleRate);
      };
      processor = node;
    }

    const activeProcessor = processor;
    const activeSink = sink;
    if (!activeProcessor || !activeSink) {
      disconnect();
      throw new Error('Audio capture failed to initialize.');
    }
    source.connect(activeProcessor);
    activeProcessor.connect(activeSink);
    activeSink.connect(context.destination);
  };

  const snapshot = () => {
    if (!sampleCount) return null;
    return encodePcm16Wav(samples.subarray(0, sampleCount));
  };

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    disconnect();
    if (context) {
      void context.close().catch(() => undefined);
      context = null;
    }
    samples = new Float32Array(0);
    sampleCount = 0;
    speechSampleCount = 0;
  };

  return {
    prepare,
    start,
    snapshot,
    hasSpeechSince: (sampleOffset) =>
      speechSampleCount > Math.max(0, sampleOffset),
    get sampleCount() {
      return sampleCount;
    },
    dispose,
  };
}
