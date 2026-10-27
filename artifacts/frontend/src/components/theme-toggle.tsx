import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Sun, Moon, Monitor } from "lucide-react";
import { isThemePreference, DEFAULT_THEME_PREFERENCE, type ThemePreference } from "@/lib/theme";
import { cn } from "@/lib/utils";

const OPTIONS: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

/** Accessible segmented radio group: Light / Dark / System. Arrow keys move selection. */
export function ThemeToggle({ className, showLabels = false }: { className?: string; showLabels?: boolean }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const current: ThemePreference = mounted && isThemePreference(theme) ? theme : DEFAULT_THEME_PREFERENCE;

  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const i = OPTIONS.findIndex((o) => o.value === current);
    let n = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % OPTIONS.length;
    if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (i + OPTIONS.length - 1) % OPTIONS.length;
    if (n < 0) return;
    e.preventDefault();
    setTheme(OPTIONS[n].value);
    (e.currentTarget.querySelectorAll<HTMLButtonElement>("[role=radio]")[n])?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-label="Color theme"
      onKeyDown={onKey}
      className={cn("inline-flex items-center gap-0.5 rounded-md border border-border bg-muted/60 p-0.5", className)}
      data-testid="theme-toggle"
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const active = current === value;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={`${label} theme`}
            title={`${label} theme`}
            tabIndex={active ? 0 : -1}
            onClick={() => setTheme(value)}
            data-testid={`button-theme-${value}`}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-[3px] px-2 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active ? "bg-card text-foreground shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            {showLabels && <span>{label}</span>}
          </button>
        );
      })}
    </div>
  );
}
