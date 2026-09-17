import { useState, useRef, useEffect, useCallback } from 'react';
import { transcribeSpeech } from '../../../../lib/api-client-react/src/generated/api';

let globalActiveSession: number | null = null;
let sessionCounter = 0;

export type VoiceInputStatus = 'idle' | 'recording' | 'transcribing' | 'error';

export function useVoiceInput(onInsert: (text: string) => void) {
  const [status, setStatus] = useState<VoiceInputStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const [recordingTime, setRecordingTime] = useState(0);

  const isMounted = useRef(true);
  const sessionRef = useRef<number | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const sizeRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const cleanupMedia = useCallback(() => {
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (mediaRecorderRef.current) {
      mediaRecorderRef.current.onstop = null;
      mediaRecorderRef.current.ondataavailable = null;
      mediaRecorderRef.current.onerror = null;
      if (mediaRecorderRef.current.state !== 'inactive') {
        try {
          mediaRecorderRef.current.stop();
        } catch (e) {
          // Ignore state errors during cleanup
        }
      }
      mediaRecorderRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }, []);

  const cancelRecording = useCallback(() => {
    cleanupMedia();
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    
    if (sessionRef.current !== null && globalActiveSession === sessionRef.current) {
      globalActiveSession = null;
    }
    sessionRef.current = null;
    
    if (isMounted.current) {
      setStatus('idle');
      setRecordingTime(0);
      setError(null);
    }
  }, [cleanupMedia]);

  useEffect(() => {
    isMounted.current = true;
    return () => {
      isMounted.current = false;
      cancelRecording();
    };
  }, [cancelRecording]);

  const processAudio = async (blob: Blob) => {
    if (!isMounted.current) return;
    const mySession = sessionRef.current;
    
    setStatus('transcribing');
    const abortCtrl = new AbortController();
    abortControllerRef.current = abortCtrl;
    
    try {
      const res = await transcribeSpeech(blob, {
        signal: abortCtrl.signal,
      });

      if (!isMounted.current || sessionRef.current !== mySession) return;

      if (res && res.text) {
        onInsert(res.text);
      }
      setStatus('idle');
    } catch (err: any) {
      if (!isMounted.current || sessionRef.current !== mySession) return;
      
      if (err.name === 'AbortError') {
        // Ignored, user cancelled or unmounted
      } else if (err.status === 503) {
        setError('Local transcription service is currently unavailable.');
        setStatus('error');
      } else {
        console.error('Transcription error:', err);
        setError(err.message || 'Failed to transcribe audio.');
        setStatus('error');
      }
    } finally {
      if (sessionRef.current === mySession) {
        if (abortControllerRef.current === abortCtrl) abortControllerRef.current = null;
        if (globalActiveSession === mySession) globalActiveSession = null;
        sessionRef.current = null;
      }
    }
  };

  const stopRecording = useCallback(() => {
    if (!isMounted.current || status !== 'recording' || !mediaRecorderRef.current) return;

    try {
      mediaRecorderRef.current.stop();
    } catch (e) {
      // Ignore
    }
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, [status]);

  const startRecording = useCallback(async () => {
    if (globalActiveSession !== null) {
      setError('Another recording is already in progress.');
      setStatus('error');
      return;
    }
    
    if (typeof window !== 'undefined' && !window.isSecureContext) {
      setError('Microphone requires a secure context (HTTPS or localhost).');
      setStatus('error');
      return;
    }
    
    if (typeof window === 'undefined' || !window.MediaRecorder) {
      setError('Audio recording is not supported in this browser.');
      setStatus('error');
      return;
    }
    
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setError('Microphone not supported in this browser.');
      setStatus('error');
      return;
    }

    setError(null);
    const mySession = ++sessionCounter;
    globalActiveSession = mySession;
    sessionRef.current = mySession;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      // Permission race: component unmounted, recording cancelled, or session changed while waiting
      if (!isMounted.current || sessionRef.current !== mySession) {
        stream.getTracks().forEach(t => t.stop());
        if (globalActiveSession === mySession) globalActiveSession = null;
        return;
      }

      streamRef.current = stream;

      const mimeType =
        [
          'audio/webm;codecs=opus',
          'audio/webm',
          'audio/ogg;codecs=opus',
          'audio/ogg',
          'audio/mp4',
        ].find((type) => MediaRecorder.isTypeSupported(type)) || '';

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];
      sizeRef.current = 0;
      setRecordingTime(0);

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          chunksRef.current.push(e.data);
          sizeRef.current += e.data.size;
          // 8 MiB limit
          if (sizeRef.current >= 8 * 1024 * 1024) {
            recorder.stop();
          }
        }
      };

      recorder.onstop = () => {
        const currentSession = sessionRef.current;
        const blob = new Blob(chunksRef.current, { type: mimeType || 'audio/webm' });
        cleanupMedia();
        if (currentSession === mySession && isMounted.current) {
          if (blob.size > 0) {
            processAudio(blob);
          } else {
            if (globalActiveSession === mySession) globalActiveSession = null;
            sessionRef.current = null;
            setStatus('idle');
          }
        }
      };

      recorder.onerror = (e: any) => {
        cleanupMedia();
        if (sessionRef.current === mySession && isMounted.current) {
          if (globalActiveSession === mySession) globalActiveSession = null;
          sessionRef.current = null;
          setError(e.error?.message || 'Error capturing audio.');
          setStatus('error');
        }
      };

      recorder.start(1000);
      setStatus('recording');

      timerRef.current = window.setInterval(() => {
        if (!isMounted.current || sessionRef.current !== mySession) {
          window.clearInterval(timerRef.current!);
          timerRef.current = null;
          return;
        }
        setRecordingTime((t) => {
          const next = t + 1;
          if (next >= 60) {
            if (mediaRecorderRef.current?.state === 'recording') {
              mediaRecorderRef.current.stop();
            }
          }
          return next;
        });
      }, 1000);
    } catch (err: any) {
      if (globalActiveSession === mySession) {
        globalActiveSession = null;
      }
      
      if (!isMounted.current || sessionRef.current !== mySession) {
        return; // Ignore errors if we cancelled while waiting
      }
      
      sessionRef.current = null;
      cleanupMedia();
      
      if (err.name === 'NotAllowedError') {
        setError('Microphone access denied.');
      } else {
        setError(err.message || 'Failed to access microphone.');
      }
      setStatus('error');
    }
  }, [cleanupMedia]);

  return {
    status,
    error,
    recordingTime,
    startRecording,
    stopRecording,
    cancelRecording,
  };
}