import * as React from "react";
import { Mic, Square, X, Loader2, AlertCircle } from "lucide-react";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { useVoiceInput } from "../hooks/use-voice-input";
import { cn } from "@/lib/utils";

function insertTextAtCursor(input: HTMLInputElement | HTMLTextAreaElement, text: string) {
  input.focus();
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? input.value.length;
  const value = input.value;
  
  let prefix = "";
  let suffix = "";
  
  if (start > 0 && !/\s/.test(value[start - 1])) {
    prefix = " ";
  }
  if (end < value.length && !/\s/.test(value[end])) {
    suffix = " ";
  }

  let toInsert = prefix + text + suffix;
  
  const maxLengthAttr = input.getAttribute('maxlength');
  if (maxLengthAttr) {
    const maxLength = parseInt(maxLengthAttr, 10);
    if (!isNaN(maxLength) && maxLength > 0) {
      const remaining = maxLength - (value.length - (end - start));
      if (remaining < toInsert.length) {
        toInsert = toInsert.substring(0, Math.max(0, remaining));
      }
    }
  }

  if (!toInsert && text) return;

  const before = value.substring(0, start);
  const after = value.substring(end);
  
  let success = false;
  try {
    success = document.execCommand('insertText', false, toInsert);
  } catch (e) {
    // Ignore and fallback
  }

  if (!success) {
    const nativeSetter = Object.getOwnPropertyDescriptor(
      Object.getPrototypeOf(input),
      'value'
    )?.set;
    
    if (nativeSetter) {
      nativeSetter.call(input, before + toInsert + after);
      input.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
    } else {
      input.value = before + toInsert + after;
      input.dispatchEvent(new Event('input', { bubbles: true, cancelable: true }));
    }
    
    const newPos = start + toInsert.length;
    input.setSelectionRange(newPos, newPos);
  }
}

function mergeRefs<T>(...refs: (React.Ref<T> | undefined)[]) {
  return (value: T | null) => {
    refs.forEach((ref) => {
      if (typeof ref === "function") {
        ref(value);
      } else if (ref != null) {
        (ref as React.MutableRefObject<T | null>).current = value;
      }
    });
  };
}

const formatTime = (seconds: number) => {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
};

export interface VoiceInputProps extends React.ComponentProps<"input"> {
  wrapperClassName?: string;
  voiceLabel?: string;
  testId?: string;
}

export const VoiceInput = React.forwardRef<HTMLInputElement, VoiceInputProps>(
  ({ className, wrapperClassName, voiceLabel, testId = 'voice', type, disabled, readOnly, ...props }, forwardedRef) => {
    const internalRef = React.useRef<HTMLInputElement>(null);
    
    const handleInsert = React.useCallback((text: string) => {
      if (internalRef.current) {
        insertTextAtCursor(internalRef.current, text);
      }
    }, []);

    const {
      status,
      error,
      recordingTime,
      startRecording,
      stopRecording,
      cancelRecording
    } = useVoiceInput(handleInsert);

    const isRestrictedType = type === 'password' || type === 'email' || type === 'number';
    const canUseVoice = !isRestrictedType && !disabled && !readOnly;

    React.useEffect(() => {
      if (!canUseVoice) {
        cancelRecording();
      }
    }, [canUseVoice, cancelRecording]);

    return (
      <div className={cn("w-full flex flex-col gap-1.5", wrapperClassName)}>
        <div className="relative w-full flex items-center group">
          <Input
            ref={mergeRefs(internalRef, forwardedRef)}
            type={type}
            disabled={disabled}
            readOnly={readOnly}
            className={cn(canUseVoice && "pr-10", className)}
            {...props}
          />
          {canUseVoice && (
            <div className="absolute right-1 top-0 bottom-0 flex items-center justify-center">
              {(status === 'idle' || status === 'error') && (
                <button
                  type="button"
                  onClick={startRecording}
                  title="Dictate text — audio is processed on your OBTV server"
                  aria-label={voiceLabel || "Start voice dictation"}
                  aria-pressed={false}
                  data-testid={`${testId}-start`}
                  className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-secondary rounded-md transition-colors"
                >
                  <Mic className="w-4 h-4" />
                </button>
              )}
              {status === 'recording' && (
                <div className="flex items-center bg-popover rounded-md border border-border shadow-sm p-0.5 animate-in fade-in zoom-in-95 duration-200">
                  <span className="text-[10px] text-destructive font-mono px-1.5 w-9 text-center animate-pulse">
                    {formatTime(recordingTime)}
                  </span>
                  <button
                    type="button"
                    onClick={stopRecording}
                    aria-label="Stop and transcribe"
                    aria-pressed={true}
                    data-testid={`${testId}-stop`}
                    className="p-1 text-destructive hover:bg-destructive/20 rounded-sm transition-colors"
                  >
                    <Square className="w-3.5 h-3.5 fill-current" />
                  </button>
                  <button
                    type="button"
                    onClick={cancelRecording}
                    aria-label="Cancel recording"
                    data-testid={`${testId}-cancel`}
                    className="p-1 text-muted-foreground hover:bg-secondary rounded-sm transition-colors ml-0.5"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
              {status === 'transcribing' && (
                <div className="flex items-center gap-1 p-1.5 text-primary">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <button type="button" onClick={cancelRecording} aria-label="Cancel transcription" data-testid={`${testId}-cancel`}><X className="w-4 h-4" /></button>
                </div>
              )}
            </div>
          )}
        </div>
        
        {(status === 'transcribing' || error) && (
          <div className="text-[11px] text-muted-foreground flex items-center justify-between px-1 animate-in fade-in duration-300">
            {status === 'transcribing' && (
              <span className="flex items-center gap-1.5 opacity-80">
                Transcribing on your OBTV server. First use may need a model download.
              </span>
            )}
            {error && (
              <span className="text-destructive flex items-center gap-1">
                <AlertCircle className="w-3 h-3" />
                {error}
              </span>
            )}
          </div>
        )}
      </div>
    );
  }
);
VoiceInput.displayName = "VoiceInput";

export interface VoiceTextareaProps extends React.ComponentProps<"textarea"> {
  wrapperClassName?: string;
  voiceLabel?: string;
  testId?: string;
}

export const VoiceTextarea = React.forwardRef<HTMLTextAreaElement, VoiceTextareaProps>(
  ({ className, wrapperClassName, voiceLabel, testId = 'voice-textarea', disabled, readOnly, ...props }, forwardedRef) => {
    const internalRef = React.useRef<HTMLTextAreaElement>(null);
    
    const handleInsert = React.useCallback((text: string) => {
      if (internalRef.current) {
        insertTextAtCursor(internalRef.current, text);
      }
    }, []);

    const {
      status,
      error,
      recordingTime,
      startRecording,
      stopRecording,
      cancelRecording
    } = useVoiceInput(handleInsert);

    const canUseVoice = !disabled && !readOnly;

    React.useEffect(() => {
      if (!canUseVoice) {
        cancelRecording();
      }
    }, [canUseVoice, cancelRecording]);

    return (
      <div className={cn("w-full flex flex-col gap-1.5", wrapperClassName)}>
        <div className="relative w-full flex flex-col group">
          <Textarea
            ref={mergeRefs(internalRef, forwardedRef)}
            disabled={disabled}
            readOnly={readOnly}
            className={cn(canUseVoice && "pb-9", className)}
            {...props}
          />
          {canUseVoice && (
            <div className="absolute right-2 bottom-2 flex items-center justify-center">
              {(status === 'idle' || status === 'error') && (
                <button
                  type="button"
                  onClick={startRecording}
                  title="Dictate text — audio is processed on your OBTV server"
                  aria-label={voiceLabel || "Start voice dictation"}
                  aria-pressed={false}
                  data-testid={`${testId}-start`}
                  className="p-1.5 text-muted-foreground bg-background/50 hover:text-foreground hover:bg-secondary border border-transparent hover:border-border rounded-md backdrop-blur-sm transition-all"
                >
                  <Mic className="w-4 h-4" />
                </button>
              )}
              {status === 'recording' && (
                <div className="flex items-center bg-popover rounded-md border border-border shadow-sm p-0.5 animate-in fade-in zoom-in-95 duration-200">
                  <span className="text-[10px] text-destructive font-mono px-1.5 w-9 text-center animate-pulse">
                    {formatTime(recordingTime)}
                  </span>
                  <button
                    type="button"
                    onClick={stopRecording}
                    aria-label="Stop and transcribe"
                    aria-pressed={true}
                    data-testid={`${testId}-stop`}
                    className="p-1 text-destructive hover:bg-destructive/20 rounded-sm transition-colors"
                  >
                    <Square className="w-3.5 h-3.5 fill-current" />
                  </button>
                  <button
                    type="button"
                    onClick={cancelRecording}
                    aria-label="Cancel recording"
                    data-testid={`${testId}-cancel`}
                    className="p-1 text-muted-foreground hover:bg-secondary rounded-sm transition-colors ml-0.5"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
              {status === 'transcribing' && (
                <div className="flex items-center gap-1 p-1.5 text-primary bg-background/50 rounded-md backdrop-blur-sm">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <button type="button" onClick={cancelRecording} aria-label="Cancel transcription" data-testid={`${testId}-cancel`}><X className="w-4 h-4" /></button>
                </div>
              )}
            </div>
          )}
        </div>
        
        {(status === 'transcribing' || error) && (
          <div className="text-[11px] text-muted-foreground flex items-center justify-between px-1 animate-in fade-in duration-300">
            {status === 'transcribing' && (
              <span className="flex items-center gap-1.5 opacity-80">
                Transcribing on your OBTV server. First use may need a model download.
              </span>
            )}
            {error && (
              <span className="text-destructive flex items-center gap-1">
                <AlertCircle className="w-3 h-3" />
                {error}
              </span>
            )}
          </div>
        )}
      </div>
    );
  }
);
VoiceTextarea.displayName = "VoiceTextarea";