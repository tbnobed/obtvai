import { useCallback, useEffect, useRef, useState } from 'react';
import { transcribeSpeech } from '../../../../lib/api-client-react/src/generated/api';
import {
  createAudioCapture,
  DICTATION_MAX_REQUEST_BYTES,
  DICTATION_MAX_SECONDS,
  type AudioCapture,
} from './audio-capture';

let globalActiveSession: number | null = null;
let sessionCounter = 0;

export type VoiceInputStatus =
  | 'idle'
  | 'requesting'
  | 'recording'
  | 'transcribing'
  | 'error';

export interface VoiceInputCallbacks {
  onStart: () => void;
  onTranscript: (text: string, final: boolean) => void;
  onCancel: () => void;
  onError: () => void;
}

interface Session {
  id: number;
  capture: AudioCapture;
  stream: MediaStream | null;
  timer: number | null;
  request: AbortController | null;
  pending: { blob: Blob; partial: boolean } | null;
  stopRequested: boolean;
  finalDelivered: boolean;
  lastPartialSampleCount: number;
  lastPartialAt: number;
  elapsedSeconds: number;
}

type LegacyCallbacks = VoiceInputCallbacks | ((text: string) => void);

const isAbortError = (error: unknown) =>
  Boolean(error && typeof error === 'object' && 'name' in error && error.name === 'AbortError');

const errorMessage = (error: unknown) => {
  if (error && typeof error === 'object' && 'message' in error) {
    return String(error.message);
  }
  return 'Failed to capture or transcribe audio.';
};

/**
 * Live, self-hosted dictation. A partial request never owns the microphone
 * lifecycle: only the current session does, so stale permission/request
 * callbacks cannot affect a newer input.
 *
 * The overload accepting a function keeps existing consumers source-compatible
 * while the callbacks object is the public live-recording contract.
 */
export function useVoiceInput(callbacks: VoiceInputCallbacks): VoiceInputResult;
export function useVoiceInput(onInsert: (text: string) => void): VoiceInputResult;
export function useVoiceInput(input: LegacyCallbacks): VoiceInputResult {
  const callbacksRef = useRef<VoiceInputCallbacks>(
    typeof input === 'function'
      ? {
          onStart: () => undefined,
          onTranscript: (text, final) => {
            if (final) input(text);
          },
          onCancel: () => undefined,
          onError: () => undefined,
        }
      : input,
  );
  // Assignment (rather than a dependency-bound callback) keeps the latest
  // editor caret callbacks visible to delayed partial/final responses.
  callbacksRef.current =
    typeof input === 'function'
      ? {
          onStart: () => undefined,
          onTranscript: (text, final) => {
            if (final) input(text);
          },
          onCancel: () => undefined,
          onError: () => undefined,
        }
      : input;

  const [status, setStatus] = useState<VoiceInputStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [recordingTime, setRecordingTime] = useState(0);
  const mountedRef = useRef(true);
  const sessionRef = useRef<Session | null>(null);

  const finishSession = useCallback(
    (session: Session, nextStatus: VoiceInputStatus = 'idle') => {
      if (session.timer !== null) {
        window.clearInterval(session.timer);
        session.timer = null;
      }
      session.capture.dispose();
      session.stream?.getTracks().forEach((track) => track.stop());
      session.stream = null;
      if (globalActiveSession === session.id) globalActiveSession = null;
      if (sessionRef.current === session) sessionRef.current = null;
      if (mountedRef.current) {
        setRecordingTime(0);
        setStatus(nextStatus);
      }
    },
    [],
  );

  const markError = useCallback(
    (session: Session, message: string) => {
      if (sessionRef.current !== session || !mountedRef.current) return;
      session.request?.abort();
      session.request = null;
      finishSession(session, 'error');
      setError(message);
      callbacksRef.current.onError();
    },
    [finishSession],
  );

  const sendSnapshot = useCallback(
    (session: Session, blob: Blob, partial: boolean) => {
      if (sessionRef.current !== session || session.finalDelivered) return;
      if (session.request) {
        // Only the newest cumulative WAV matters. This is the coalescing
        // queue: no request can be overtaken by an older snapshot.
        session.pending = { blob, partial };
        return;
      }

      const controller = new AbortController();
      session.request = controller;
      if (!partial && mountedRef.current) setStatus('transcribing');

      // New generated clients take (blob, { partial }, { signal }); keeping
      // this call shape also makes request cancellation explicit.
      void transcribeSpeech(blob, { partial }, { signal: controller.signal })
        .then((result) => {
          if (sessionRef.current !== session || session.finalDelivered) return;
          const text = typeof result?.text === 'string' ? result.text : '';
          if (partial) {
            // Empty partials must not erase the editor's visible interim text.
            if (text.trim()) callbacksRef.current.onTranscript(text, false);
            if (
              mountedRef.current &&
              !session.stopRequested &&
              sessionRef.current === session
            ) {
              setStatus('recording');
            }
          } else {
            session.finalDelivered = true;
            callbacksRef.current.onTranscript(text, true);
            // A final callback may synchronously cancel the input (for
            // example, a controlled editor replacing its text region).
            if (sessionRef.current === session) finishSession(session);
          }
        })
        .catch((requestError: unknown) => {
          if (sessionRef.current !== session || !mountedRef.current) return;
          if (isAbortError(requestError)) return;
          markError(session, errorMessage(requestError));
        })
        .finally(() => {
          if (session.request === controller) session.request = null;
          if (sessionRef.current !== session || session.finalDelivered) return;
          if (session.pending) {
            const pending = session.pending;
            session.pending = null;
            sendSnapshot(session, pending.blob, pending.partial);
          } else if (session.stopRequested) {
            // stopRecording always enqueues a final snapshot, but this guard
            // protects against a capture ending with no samples.
            finishSession(session);
          }
        });
    },
    [finishSession, markError],
  );

  const queueSnapshot = useCallback(
    (session: Session, partial: boolean) => {
      const blob = session.capture.snapshot();
      if (!blob) {
        if (!partial) finishSession(session);
        return;
      }
      if (blob.size > DICTATION_MAX_REQUEST_BYTES) {
        markError(session, 'Audio snapshot exceeds the 8 MiB limit.');
        return;
      }
      sendSnapshot(session, blob, partial);
    },
    [finishSession, markError, sendSnapshot],
  );

  const stopRecording = useCallback(() => {
    const session = sessionRef.current;
    if (!session || session.stopRequested) return;
    session.stopRequested = true;
    if (mountedRef.current) setStatus('transcribing');
    if (session.timer !== null) {
      window.clearInterval(session.timer);
      session.timer = null;
    }
    // Snapshot before stopping the stream/context. One final request is
    // queued behind any partial currently in flight.
    const finalBlob = session.capture.snapshot();
    session.capture.dispose();
    session.stream?.getTracks().forEach((track) => track.stop());
    session.stream = null;
    if (finalBlob) {
      if (session.request) session.pending = { blob: finalBlob, partial: false };
      else sendSnapshot(session, finalBlob, false);
    } else if (!session.request) {
      finishSession(session);
    }
  }, [finishSession, sendSnapshot]);

  const cancelRecording = useCallback(() => {
    const session = sessionRef.current;
    if (!session) return;
    sessionRef.current = null;
    session.request?.abort();
    session.request = null;
    finishSession(session);
    // A mounted, user-initiated cancellation is observable. Unmount cleanup
    // uses the same resource path but intentionally does not call this.
    if (mountedRef.current) callbacksRef.current.onCancel();
  }, [finishSession]);

  const startRecording = useCallback(async () => {
    if (globalActiveSession !== null) {
      if (mountedRef.current) {
        setError('Another recording is already in progress.');
        setStatus('error');
        callbacksRef.current.onError();
      }
      return;
    }
    if (typeof window === 'undefined' || !window.isSecureContext) {
      setError('Microphone requires a secure context (HTTPS or localhost).');
      setStatus('error');
      callbacksRef.current.onError();
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Microphone is not supported in this browser.');
      setStatus('error');
      callbacksRef.current.onError();
      return;
    }

    let ownedSession: Session | null = null;
    let capture: AudioCapture | null = null;
    try {
      capture = createAudioCapture({
        onError: (captureError) => {
          if (ownedSession && sessionRef.current === ownedSession) {
            markError(ownedSession, errorMessage(captureError));
          }
        },
      });
      // Prepare and notify before awaiting permission so editors can capture
      // the caret in the initiating click handler.
      capture.prepare();
    } catch (captureError: unknown) {
      capture?.dispose();
      if (mountedRef.current) {
        setError(errorMessage(captureError));
        setStatus('error');
        callbacksRef.current.onError();
      }
      return;
    }
    if (!capture) return;
    try {
      callbacksRef.current.onStart();
    } catch (callbackError: unknown) {
      capture.dispose();
      if (mountedRef.current) {
        setError(errorMessage(callbackError));
        setStatus('error');
        callbacksRef.current.onError();
      }
      return;
    }
    const session: Session = {
      id: ++sessionCounter,
      capture,
      stream: null,
      timer: null,
      request: null,
      pending: null,
      stopRequested: false,
      finalDelivered: false,
      lastPartialSampleCount: 0,
      lastPartialAt: Date.now(),
      elapsedSeconds: 0,
    };
    ownedSession = session;
    globalActiveSession = session.id;
    sessionRef.current = session;
    setError(null);
    setRecordingTime(0);
    setStatus('requesting');

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current || sessionRef.current !== session) {
        stream.getTracks().forEach((track) => track.stop());
        capture.dispose();
        if (globalActiveSession === session.id) globalActiveSession = null;
        return;
      }
      session.stream = stream;
      await capture.start(stream);
      if (!mountedRef.current || sessionRef.current !== session) return;
      setStatus('recording');
      session.timer = window.setInterval(() => {
        if (sessionRef.current !== session || session.stopRequested) return;
        session.elapsedSeconds += 1;
        if (session.elapsedSeconds >= DICTATION_MAX_SECONDS) {
          setRecordingTime(DICTATION_MAX_SECONDS);
          stopRecording();
          return;
        }
        setRecordingTime(session.elapsedSeconds);
        if (
          Date.now() - session.lastPartialAt >= 2_000 &&
          session.capture.sampleCount > session.lastPartialSampleCount &&
          session.capture.hasSpeechSince(session.lastPartialSampleCount)
        ) {
          session.lastPartialAt = Date.now();
          session.lastPartialSampleCount = session.capture.sampleCount;
          queueSnapshot(session, true);
        }
      }, 1000);
    } catch (startError: unknown) {
      if (!mountedRef.current || sessionRef.current !== session) {
        capture.dispose();
        return;
      }
      const message =
        startError && typeof startError === 'object' && 'name' in startError &&
        startError.name === 'NotAllowedError'
          ? 'Microphone access denied.'
          : errorMessage(startError);
      markError(session, message);
    }
  }, [markError, queueSnapshot, stopRecording]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const session = sessionRef.current;
      if (!session) return;
      sessionRef.current = null;
      session.request?.abort();
      session.request = null;
      if (session.timer !== null) window.clearInterval(session.timer);
      session.capture.dispose();
      session.stream?.getTracks().forEach((track) => track.stop());
      if (globalActiveSession === session.id) globalActiveSession = null;
    };
  }, []);

  return {
    status,
    error,
    recordingTime,
    startRecording,
    stopRecording,
    cancelRecording,
  };
}

export interface VoiceInputResult {
  status: VoiceInputStatus;
  error: string | null;
  recordingTime: number;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  cancelRecording: () => void;
}
