import * as React from "react";
import { AlertCircle, Loader2, Mic, Square, X } from "lucide-react";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { useVoiceInput } from "../hooks/use-voice-input";
import { cn } from "@/lib/utils";
import {
  createTextRegion,
  replaceTextRegion,
  restoreTextRegion,
  type TextRegion,
} from "./voice-text-region";

type VoiceElement = HTMLInputElement | HTMLTextAreaElement;
type VoiceInputCallbacks = {
  onStart: () => void;
  onTranscript: (text: string, final: boolean) => void;
  onCancel: () => void;
  onError: () => void;
};

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
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds % 60).toString().padStart(2, "0")}`;
};

const dictationTitle =
  "Dictate text — processed by your OBTV server; maximum 60 seconds";

function nativeValueSetter(input: VoiceElement) {
  let prototype: object | null = Object.getPrototypeOf(input);
  while (prototype) {
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (setter) return setter;
    prototype = Object.getPrototypeOf(prototype);
  }
  return null;
}

function maxLengthFor(input: VoiceElement): number | undefined {
  const attribute = input.getAttribute("maxlength");
  if (attribute === null) return undefined;
  const value = Number(attribute);
  return Number.isFinite(value) && value >= 0 ? value : undefined;
}

interface DictationFieldProps {
  wrapperClassName?: string;
  canUseVoice: boolean;
  status: string;
  error: string | null;
  recordingTime: number;
  testId: string;
  voiceLabel?: string;
  startRecording: () => void;
  stopRecording: () => void;
  cancelRecording: () => void;
  children: React.ReactNode;
}

function DictationControls({
  wrapperClassName,
  canUseVoice,
  status,
  error,
  recordingTime,
  testId,
  voiceLabel,
  startRecording,
  stopRecording,
  cancelRecording,
  children,
}: DictationFieldProps) {
  const active = status === "recording" || status === "requesting" || status === "transcribing";
  const showStart = status === "idle" || status === "error";
  const statusText =
    status === "requesting"
      ? "Requesting microphone permission."
      : status === "recording"
        ? "Listening — words may update as you speak."
        : status === "transcribing"
          ? "Finalizing dictation on your OBTV server."
          : error || "";

  const statusMessage = (
    <div
      className={cn(
        "min-h-4 text-[11px] flex items-center px-1 animate-in fade-in duration-300",
        !statusText && "sr-only",
      )}
      role="status"
      aria-live="polite"
      data-testid={`${testId}-status`}
    >
      {statusText && (
        <span className={cn(error && status === "error" ? "text-destructive" : "text-muted-foreground")}>
          {error && status === "error" && <AlertCircle className="w-3 h-3 inline mr-1" />}
          {statusText}
        </span>
      )}
      {active && status !== "recording" && (
        <span className="sr-only">
          The audio is processed only by your OBTV server. The limit is 60 seconds.
        </span>
      )}
    </div>
  );

  const activeControls = (
    <>
      {status === "requesting" && (
        <div className="flex items-center gap-1 bg-popover rounded-md border border-border shadow-sm p-1">
          <Loader2 className="w-4 h-4 animate-spin text-primary" aria-hidden="true" />
          <button
            type="button"
            onClick={cancelRecording}
            aria-label="Cancel microphone permission request"
            title="Cancel"
            data-testid={`${testId}-cancel`}
            className="min-h-9 min-w-9 p-2 text-muted-foreground hover:bg-secondary rounded-md"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
      {status === "recording" && (
        <div className="flex items-center bg-popover rounded-md border border-border shadow-sm p-1">
          <span className="text-[10px] text-destructive font-mono px-1.5 w-10 text-center animate-pulse">
            {formatTime(recordingTime)}
          </span>
          <button
            type="button"
            onClick={stopRecording}
            aria-label="Stop and transcribe"
            title="Stop and transcribe"
            aria-pressed={true}
            data-testid={`${testId}-stop`}
            className="min-h-9 min-w-9 p-2 text-destructive hover:bg-destructive/20 rounded-md"
          >
            <Square className="w-4 h-4 fill-current" />
          </button>
          <button
            type="button"
            onClick={cancelRecording}
            aria-label="Cancel recording"
            title="Cancel"
            data-testid={`${testId}-cancel`}
            className="min-h-9 min-w-9 p-2 text-muted-foreground hover:bg-secondary rounded-md"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
      {status === "transcribing" && (
        <div className="flex items-center gap-1 bg-popover rounded-md border border-border shadow-sm p-1">
          <Loader2 className="w-4 h-4 animate-spin text-primary" aria-hidden="true" />
          <button
            type="button"
            onClick={cancelRecording}
            aria-label="Cancel finalizing dictation"
            title="Cancel"
            data-testid={`${testId}-cancel`}
            className="min-h-9 min-w-9 p-2 text-muted-foreground hover:bg-secondary rounded-md"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </>
  );

  return (
    <div className={cn("w-full flex flex-col gap-1.5", wrapperClassName)}>
      <div className="relative w-full flex items-center group">
        {children}
        {canUseVoice && showStart && (
          <div className="absolute right-1 top-0 bottom-0 flex items-center justify-center">
            <button
              type="button"
              onClick={startRecording}
              title={dictationTitle}
              aria-label={voiceLabel || "Start voice dictation"}
              aria-pressed={false}
              data-testid={`${testId}-start`}
              className="min-h-9 min-w-9 p-2 text-muted-foreground hover:text-foreground hover:bg-secondary rounded-md transition-colors"
            >
              <Mic className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
      {canUseVoice && active ? (
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          {statusMessage}
          <div className="ml-auto">{activeControls}</div>
        </div>
      ) : (
        statusMessage
      )}
    </div>
  );
}

function useDictationField(inputRef: React.MutableRefObject<VoiceElement | null>) {
  const regionRef = React.useRef<(TextRegion & { expectedValue: string }) | null>(null);
  const writingRef = React.useRef(false);
  const finalAppliedRef = React.useRef(false);
  const cancelRef = React.useRef<(() => void)>(() => undefined);

  const abandon = React.useCallback(() => {
    regionRef.current = null;
    finalAppliedRef.current = false;
    cancelRef.current();
  }, []);

  const capture = React.useCallback(() => {
    const input = inputRef.current;
    if (!input || input.disabled || input.readOnly) return;
    const region = createTextRegion(input.value, input.selectionStart, input.selectionEnd);
    regionRef.current = { ...region, expectedValue: input.value };
    finalAppliedRef.current = false;
  }, [inputRef]);

  const write = React.useCallback(
    (value: string, selectionStart: number, selectionEnd: number) => {
      const input = inputRef.current;
      if (!input) return false;
      if (input.disabled || input.readOnly) return false;
      const setter = nativeValueSetter(input);
      if (!setter) return false;

      writingRef.current = true;
      try {
        setter.call(input, value);
        // Keep the result visible to controlled parents synchronously, without
        // focusing a field whose focus may belong to another control.
        if (document.activeElement === input) {
          input.setSelectionRange(selectionStart, selectionEnd);
        }
        input.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
      } finally {
        writingRef.current = false;
      }
      return input.value === value;
    },
    [inputRef],
  );

  const restore = React.useCallback(() => {
    const input = inputRef.current;
    const region = regionRef.current;
    if (!input || !region) return;
    if (input.disabled || input.readOnly) {
      regionRef.current = null;
      finalAppliedRef.current = false;
      return;
    }
    const restored = restoreTextRegion(input.value, region, region.expectedValue);
    if (restored !== null) {
      write(restored, region.start, region.end);
    }
    regionRef.current = null;
    finalAppliedRef.current = false;
  }, [inputRef, write]);

  const onStart = React.useCallback(() => {
    if (!regionRef.current) capture();
  }, [capture]);

  const onTranscript = React.useCallback(
    (text: string, isFinal: boolean) => {
      if (isFinal && finalAppliedRef.current) return;
      const input = inputRef.current;
      const region = regionRef.current;
      if (!input || !region) {
        // A result without an owned field must never be inserted elsewhere.
        if (!finalAppliedRef.current) abandon();
        return;
      }
      if (input.disabled || input.readOnly) {
        abandon();
        return;
      }
      if (input.value !== region.expectedValue) {
        abandon();
        return;
      }

      const replacement = replaceTextRegion(
        input.value,
        region,
        text,
        maxLengthFor(input),
      );
      if (!replacement || !write(replacement.value, replacement.start, replacement.end)) {
        abandon();
        return;
      }
      region.ownedEnd = replacement.end;
      region.expectedValue = replacement.value;
      if (isFinal) {
        finalAppliedRef.current = true;
        regionRef.current = null;
      }
    },
    [abandon, inputRef, write],
  );

  const onCancel = React.useCallback(() => restore(), [restore]);
  const onError = React.useCallback(() => {
    // Keep already recognized words visible when finalization fails. An
    // explicit Cancel remains the path that restores the original selection.
    regionRef.current = null;
    finalAppliedRef.current = false;
  }, []);
  const callbacks = React.useMemo<VoiceInputCallbacks>(
    () => ({ onStart, onTranscript, onCancel, onError }),
    [onCancel, onError, onStart, onTranscript],
  );

  const voice = useVoiceInput(callbacks);
  cancelRef.current = voice.cancelRecording;

  const handleStart = React.useCallback(() => {
    // This is deliberately before startRecording: permission prompts are
    // asynchronous and must not change the original selection we own.
    capture();
    voice.startRecording();
  }, [capture, voice.startRecording]);

  const handleCancel = React.useCallback(() => {
    voice.cancelRecording();
  }, [voice.cancelRecording]);

  const cancelWithoutRestore = React.useCallback(() => {
    // A field becoming disabled/read-only must retain exactly what it shows;
    // only an explicit Cancel action is allowed to restore the old selection.
    regionRef.current = null;
    finalAppliedRef.current = false;
    voice.cancelRecording();
  }, [voice.cancelRecording]);

  const handleInput = React.useCallback(
    (event: React.FormEvent<VoiceElement>) => {
      if (!writingRef.current && regionRef.current) abandon();
      return event;
    },
    [abandon],
  );

  React.useEffect(() => {
    const input = inputRef.current;
    const region = regionRef.current;
    if (input && region && input.value !== region.expectedValue) abandon();
  }, [abandon, inputRef]);

  return {
    ...voice,
    handleStart,
    handleCancel,
    cancelWithoutRestore,
    handleInput,
  };
}

export interface VoiceInputProps extends React.ComponentProps<"input"> {
  wrapperClassName?: string;
  voiceLabel?: string;
  testId?: string;
}

export const VoiceInput = React.forwardRef<HTMLInputElement, VoiceInputProps>(
  (
    {
      className,
      wrapperClassName,
      voiceLabel,
      testId = "voice",
      type,
      disabled,
      readOnly,
      onInput,
      onChange,
      ...props
    },
    forwardedRef,
  ) => {
    const internalRef = React.useRef<HTMLInputElement>(null);
    const dictation = useDictationField(internalRef as React.MutableRefObject<VoiceElement | null>);
    const isRestrictedType = type === "password" || type === "email" || type === "number";
    const canUseVoice = !isRestrictedType && !disabled && !readOnly;
    const idleMic = dictation.status === "idle" || dictation.status === "error";

    React.useEffect(() => {
      if (!canUseVoice) dictation.cancelWithoutRestore();
    }, [canUseVoice, dictation.cancelWithoutRestore]);

    return (
      <DictationControls
        wrapperClassName={wrapperClassName}
        canUseVoice={canUseVoice}
        status={dictation.status}
        error={dictation.error}
        recordingTime={dictation.recordingTime}
        testId={testId}
        voiceLabel={voiceLabel}
        startRecording={dictation.handleStart}
        stopRecording={dictation.stopRecording}
        cancelRecording={dictation.handleCancel}
      >
        <Input
          ref={mergeRefs(internalRef, forwardedRef)}
          type={type}
          disabled={disabled}
          readOnly={readOnly}
          className={cn(className, canUseVoice && idleMic && "pr-12")}
          onInput={(event) => {
            dictation.handleInput(event);
            onInput?.(event);
          }}
          onChange={(event) => {
            dictation.handleInput(event);
            onChange?.(event);
          }}
          {...props}
        />
      </DictationControls>
    );
  },
);
VoiceInput.displayName = "VoiceInput";

export interface VoiceTextareaProps extends React.ComponentProps<"textarea"> {
  wrapperClassName?: string;
  voiceLabel?: string;
  testId?: string;
}

export const VoiceTextarea = React.forwardRef<HTMLTextAreaElement, VoiceTextareaProps>(
  (
    {
      className,
      wrapperClassName,
      voiceLabel,
      testId = "voice-textarea",
      disabled,
      readOnly,
      onInput,
      onChange,
      ...props
    },
    forwardedRef,
  ) => {
    const internalRef = React.useRef<HTMLTextAreaElement>(null);
    const dictation = useDictationField(internalRef as React.MutableRefObject<VoiceElement | null>);
    const canUseVoice = !disabled && !readOnly;
    const idleMic = dictation.status === "idle" || dictation.status === "error";

    React.useEffect(() => {
      if (!canUseVoice) dictation.cancelWithoutRestore();
    }, [canUseVoice, dictation.cancelWithoutRestore]);

    return (
      <DictationControls
        wrapperClassName={wrapperClassName}
        canUseVoice={canUseVoice}
        status={dictation.status}
        error={dictation.error}
        recordingTime={dictation.recordingTime}
        testId={testId}
        voiceLabel={voiceLabel}
        startRecording={dictation.handleStart}
        stopRecording={dictation.stopRecording}
        cancelRecording={dictation.handleCancel}
      >
        <Textarea
          ref={mergeRefs(internalRef, forwardedRef)}
          disabled={disabled}
          readOnly={readOnly}
          className={cn(className, canUseVoice && idleMic && "pb-10 pr-12")}
          onInput={(event) => {
            dictation.handleInput(event);
            onInput?.(event);
          }}
          onChange={(event) => {
            dictation.handleInput(event);
            onChange?.(event);
          }}
          {...props}
        />
      </DictationControls>
    );
  },
);
VoiceTextarea.displayName = "VoiceTextarea";