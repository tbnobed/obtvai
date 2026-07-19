/** Single duration format used by Dashboard and Insights: "49.6h" / "37m" / "45s". */
export function formatHours(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0m";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}
