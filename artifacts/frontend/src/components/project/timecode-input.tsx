import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { formatTC, parseTC } from "@/lib/timecode";

interface TimecodeInputProps {
  /** Seconds. */
  value: number;
  fps?: number | null;
  disabled?: boolean;
  className?: string;
  title?: string;
  onCommit: (seconds: number) => void;
}

/**
 * mm:ss.ff text field. Keeps a local string while focused so partial input
 * like "1:" isn't clobbered; commits on blur/Enter; shows an inline hint on
 * invalid input. Storage stays in seconds.
 */
export function TimecodeInput({ value, fps, disabled, className, title, onCommit }: TimecodeInputProps) {
  const f = fps && fps > 0 ? fps : 25;
  const [text, setText] = useState(() => formatTC(value, f));
  const [focused, setFocused] = useState(false);
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    if (!focused && !invalid) setText(formatTC(value, f));
  }, [value, f, focused, invalid]);

  const commit = () => {
    const parsed = parseTC(text, f);
    if (parsed == null) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setText(formatTC(parsed, f));
    if (Math.round(parsed * f) !== Math.round(value * f)) onCommit(parsed);
  };

  return (
    <div className="relative">
      <Input
        type="text"
        inputMode="numeric"
        disabled={disabled}
        title={title}
        className={`${className ?? ""} ${invalid ? "border-red-500 focus-visible:ring-red-500" : ""}`}
        value={text}
        onFocus={() => setFocused(true)}
        onBlur={() => { setFocused(false); commit(); }}
        onChange={(e) => { setText(e.target.value); setInvalid(false); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); commit(); (e.target as HTMLInputElement).blur(); }
          if (e.key === "Escape") { setInvalid(false); setText(formatTC(value, f)); (e.target as HTMLInputElement).blur(); }
          e.stopPropagation();
        }}
      />
      {invalid && (
        <span className="absolute left-0 top-full mt-0.5 whitespace-nowrap text-[10px] text-red-400 z-10">
          Use mm:ss format.
        </span>
      )}
    </div>
  );
}
