import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

const LG = "(min-width: 1024px)";

function useIsDocked() {
  const [docked, setDocked] = useState(() => typeof window !== "undefined" && window.matchMedia(LG).matches);
  useEffect(() => {
    const mq = window.matchMedia(LG);
    const on = () => setDocked(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return docked;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Docks the assistant beside the library on large screens. Below lg it becomes
 * a true modal dialog portaled to <body>, above the app sidebar (z-50) so it
 * owns hit-testing, traps focus, closes on Escape and restores focus.
 */
export function ArchiveChatDock({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const docked = useIsDocked();
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (docked) return;
    const opener = document.activeElement as HTMLElement | null;
    const root = ref.current;
    const initial = root?.querySelector<HTMLElement>("[data-testid=input-ask-archive]:not([disabled])") ?? root?.querySelector<HTMLElement>(FOCUSABLE);
    initial?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); closeRef.current(); return; }
      if (e.key !== "Tab" || !root) return;
      const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(el => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (!root.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      if (opener && document.contains(opener)) opener.focus();
    };
  }, [docked]);

  if (docked) {
    return (
      <aside className="w-[400px] xl:w-[440px] shrink-0 border-l border-border flex flex-col min-h-0" aria-label="Archive assistant" data-testid="aside-archive-chat">
        {children}
      </aside>
    );
  }
  return createPortal(
    <div ref={ref} role="dialog" aria-modal="true" aria-label="Archive assistant" className="fixed inset-0 z-[60] flex flex-col min-h-0 bg-card" data-testid="aside-archive-chat">
      {children}
    </div>,
    document.body,
  );
}
