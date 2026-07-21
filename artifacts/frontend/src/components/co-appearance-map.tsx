import { useEffect, useMemo, useRef, useState } from "react";
import { useGetCoAppearances } from "@workspace/api-client-react";
import type { CoAppearanceNode, CoAppearancePair } from "@workspace/api-client-react";
import { useLocation } from "wouter";
import { Maximize2, Share2, ZoomIn, ZoomOut } from "lucide-react";

const W = 960;
const H = 620;
const PAD = 60;
const MIN_VIEW_W = W / 8;

function formatTogether(seconds: number) {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${m}m ${Math.round(seconds % 60)}s`;
}

function nodeRadius(assetCount: number, maxAssets: number) {
  const t = maxAssets > 0 ? Math.min(assetCount / maxAssets, 1) : 0;
  return 20 + t * 14;
}

/** Deterministic force-directed layout: circle seed + repulsion, springs
 *  along edges (stronger pairs pull closer), and center gravity. */
function computeLayout(nodes: CoAppearanceNode[], pairs: CoAppearancePair[]) {
  const n = nodes.length;
  const idx = new Map(nodes.map((node, i) => [node.person_id, i]));
  const px = new Array<number>(n);
  const py = new Array<number>(n);
  const seedR = Math.min(W, H) * 0.34;
  for (let i = 0; i < n; i++) {
    const angle = (2 * Math.PI * i) / Math.max(n, 1);
    px[i] = W / 2 + seedR * Math.cos(angle);
    py[i] = H / 2 + seedR * Math.sin(angle);
  }
  const maxShared = Math.max(1, ...pairs.map((p) => p.shared_assets));
  const edges = pairs
    .map((p) => ({ a: idx.get(p.person_a_id), b: idx.get(p.person_b_id), w: p.shared_assets / maxShared }))
    .filter((e): e is { a: number; b: number; w: number } => e.a !== undefined && e.b !== undefined);

  const ITER = 300;
  for (let iter = 0; iter < ITER; iter++) {
    const cooling = 1 - iter / ITER;
    const fx = new Array<number>(n).fill(0);
    const fy = new Array<number>(n).fill(0);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        let dx = px[i] - px[j];
        let dy = py[i] - py[j];
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = (i - j) * 0.1 || 0.1; dy = 0.1; d2 = dx * dx + dy * dy; }
        const d = Math.sqrt(d2);
        const rep = 16000 / d2;
        fx[i] += (dx / d) * rep; fy[i] += (dy / d) * rep;
        fx[j] -= (dx / d) * rep; fy[j] -= (dy / d) * rep;
      }
    }
    for (const e of edges) {
      const dx = px[e.b] - px[e.a];
      const dy = py[e.b] - py[e.a];
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const target = 280 - 160 * e.w;
      const f = (d - target) * 0.03;
      fx[e.a] += (dx / d) * f; fy[e.a] += (dy / d) * f;
      fx[e.b] -= (dx / d) * f; fy[e.b] -= (dy / d) * f;
    }
    for (let i = 0; i < n; i++) {
      fx[i] += (W / 2 - px[i]) * 0.015;
      fy[i] += (H / 2 - py[i]) * 0.015;
      const step = 0.85 * cooling;
      px[i] = Math.min(W - PAD, Math.max(PAD, px[i] + fx[i] * step));
      py[i] = Math.min(H - PAD, Math.max(PAD, py[i] + fy[i] * step));
    }
  }
  return { px, py, idx };
}

const MIN_SHARED_OPTIONS = [1, 2, 3, 5] as const;

export default function CoAppearanceMap() {
  const [namedOnly, setNamedOnly] = useState(true);
  const [minShared, setMinShared] = useState<number>(1);
  const { data, isLoading } = useGetCoAppearances({ named_only: namedOnly, min_shared: minShared });
  const [, navigate] = useLocation();
  const [hoveredPair, setHoveredPair] = useState<number | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const nodes = useMemo(() => data?.nodes ?? [], [data]);
  const pairs = useMemo(
    () => [...(data?.pairs ?? [])].sort((a, b) => a.shared_assets - b.shared_assets),
    [data]
  );

  const svgRef = useRef<SVGSVGElement>(null);
  const [view, setView] = useState({ x: 0, y: 0, w: W, h: H });
  const zoomed = view.w < W - 0.5;
  const didDragRef = useRef(false);
  const panRef = useRef<{ pointerId: number; startX: number; startY: number; view: { x: number; y: number; w: number; h: number } } | null>(null);

  const clampView = (x: number, y: number, w: number) => {
    const cw = Math.min(W, Math.max(MIN_VIEW_W, w));
    const ch = cw * (H / W);
    return {
      x: Math.min(W - cw, Math.max(0, x)),
      y: Math.min(H - ch, Math.max(0, y)),
      w: cw,
      h: ch,
    };
  };

  const zoomBy = (factor: number, relX = 0.5, relY = 0.5) =>
    setView((v) => {
      const w = Math.min(W, Math.max(MIN_VIEW_W, v.w * factor));
      const scale = w / v.w;
      const cx = v.x + relX * v.w;
      const cy = v.y + relY * v.h;
      return clampView(cx - (cx - v.x) * scale, cy - (cy - v.y) * scale, w);
    });

  const resetView = () => setView({ x: 0, y: 0, w: W, h: H });

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      zoomBy(e.deltaY > 0 ? 1.25 : 1 / 1.25, (e.clientX - rect.left) / rect.width, (e.clientY - rect.top) / rect.height);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, nodes.length]);

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    didDragRef.current = false;
    panRef.current = { pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, view };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const pan = panRef.current;
    if (!pan || pan.pointerId !== e.pointerId) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const dxPx = e.clientX - pan.startX;
    const dyPx = e.clientY - pan.startY;
    if (Math.abs(dxPx) + Math.abs(dyPx) > 4) didDragRef.current = true;
    setView(clampView(pan.view.x - (dxPx / rect.width) * pan.view.w, pan.view.y - (dyPx / rect.height) * pan.view.h, pan.view.w));
  };
  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (panRef.current?.pointerId === e.pointerId) panRef.current = null;
  };

  const layout = useMemo(() => computeLayout(nodes, pairs), [nodes, pairs]);
  const nameOf = useMemo(() => new Map(nodes.map((n) => [n.person_id, n.display_name])), [nodes]);
  const maxAssets = useMemo(() => Math.max(1, ...nodes.map((n) => n.asset_count)), [nodes]);
  const maxShared = useMemo(() => Math.max(1, ...pairs.map((p) => p.shared_assets)), [pairs]);

  const connectedTo = useMemo(() => {
    if (!hoveredNode) return null;
    const set = new Set<string>([hoveredNode]);
    for (const p of pairs) {
      if (p.person_a_id === hoveredNode) set.add(p.person_b_id);
      if (p.person_b_id === hoveredNode) set.add(p.person_a_id);
    }
    return set;
  }, [hoveredNode, pairs]);

  const hovered = (hoveredPair !== null ? pairs[hoveredPair] : null) ?? null;

  const controls = (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
      <label className="flex items-center gap-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={namedOnly}
          onChange={(e) => setNamedOnly(e.target.checked)}
          className="h-4 w-4 accent-primary"
        />
        <span>Named people only</span>
      </label>
      <label className="flex items-center gap-2">
        <span className="text-muted-foreground">Min shared videos</span>
        <select
          value={minShared}
          onChange={(e) => setMinShared(Number(e.target.value))}
          className="bg-card border border-border rounded px-2 py-1 text-sm"
        >
          {MIN_SHARED_OPTIONS.map((n) => (
            <option key={n} value={n}>{n}+</option>
          ))}
        </select>
      </label>
      {!isLoading && (
        <span className="text-xs text-muted-foreground ml-auto">
          {nodes.length} {nodes.length === 1 ? "person" : "people"} · {pairs.length} {pairs.length === 1 ? "connection" : "connections"}
        </span>
      )}
    </div>
  );

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        {controls}
        <div className="animate-pulse bg-muted rounded-md w-full" style={{ aspectRatio: `${W}/${H}` }} />
      </div>
    );
  }

  if (!nodes.length) {
    return (
      <div className="flex flex-col gap-3">
        {controls}
        <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground py-24">
          <Share2 className="h-12 w-12 mb-4 opacity-50" />
          {namedOnly ? (
            <>
              <p>No named people match these filters.</p>
              <p className="text-xs mt-1 max-w-md text-center">
                Name people (rename them or enroll from a photo) to see them here, or untick "Named people only" to show everyone detected.
              </p>
            </>
          ) : (
            <>
              <p>No people identified yet.</p>
              <p className="text-xs mt-1 max-w-md text-center">
                The map fills in as people are identified in your videos. Lines appear when two people share a video.
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {controls}
      <div className="relative border border-border bg-card rounded-md overflow-hidden">
        <svg
          ref={svgRef}
          viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
          className="w-full h-auto block touch-none select-none"
          style={{ cursor: panRef.current ? "grabbing" : zoomed ? "grab" : "default" }}
          role="img"
          aria-label="Co-appearance map"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        >
          {pairs.map((p, i) => {
            const a = layout.idx.get(p.person_a_id);
            const b = layout.idx.get(p.person_b_id);
            if (a === undefined || b === undefined) return null;
            const strong = hoveredPair === i;
            const dimmed =
              (hoveredPair !== null && !strong) ||
              (connectedTo !== null && !(connectedTo.has(p.person_a_id) && connectedTo.has(p.person_b_id) && (p.person_a_id === hoveredNode || p.person_b_id === hoveredNode)));
            return (
              <line
                key={i}
                x1={layout.px[a]} y1={layout.py[a]}
                x2={layout.px[b]} y2={layout.py[b]}
                stroke="currentColor"
                className={strong ? "text-primary" : dimmed ? "text-border/40" : "text-border"}
                strokeWidth={1.5 + (p.shared_assets / maxShared) * 6}
                strokeLinecap="round"
                style={{ cursor: "pointer" }}
                onMouseEnter={() => setHoveredPair(i)}
                onMouseLeave={() => setHoveredPair(null)}
              />
            );
          })}
          {nodes.map((node) => {
            const i = layout.idx.get(node.person_id);
            if (i === undefined) return null;
            const x = layout.px[i];
            const y = layout.py[i];
            const r = nodeRadius(node.asset_count, maxAssets);
            const inHoveredPair =
              hovered !== null && (hovered.person_a_id === node.person_id || hovered.person_b_id === node.person_id);
            const dimmed =
              (connectedTo !== null && !connectedTo.has(node.person_id)) ||
              (hovered !== null && !inHoveredPair);
            const initials = node.display_name
              .split(/\s+/)
              .map((w) => w[0])
              .filter(Boolean)
              .slice(0, 2)
              .join("")
              .toUpperCase();
            return (
              <g
                key={node.person_id}
                style={{ cursor: "pointer", opacity: dimmed ? 0.3 : 1, transition: "opacity 120ms" }}
                onClick={() => {
                  if (didDragRef.current) return;
                  navigate(`/people/${node.person_id}`);
                }}
                onMouseEnter={() => setHoveredNode(node.person_id)}
                onMouseLeave={() => setHoveredNode(null)}
              >
                <title>{`${node.display_name} — ${node.asset_count} ${node.asset_count === 1 ? "video" : "videos"}`}</title>
                <circle cx={x} cy={y} r={r + 2} className="fill-card stroke-primary/60" strokeWidth={hoveredNode === node.person_id || inHoveredPair ? 2.5 : 1} />
                {node.thumbnail_url ? (
                  <>
                    <clipPath id={`clip-${node.person_id}`}>
                      <circle cx={x} cy={y} r={r} />
                    </clipPath>
                    <image
                      href={`/api/thumbnails/${node.thumbnail_url}`}
                      x={x - r} y={y - r} width={r * 2} height={r * 2}
                      clipPath={`url(#clip-${node.person_id})`}
                      preserveAspectRatio="xMidYMid slice"
                    />
                  </>
                ) : (
                  <>
                    <circle cx={x} cy={y} r={r} className="fill-muted" />
                    <text x={x} y={y + 1} textAnchor="middle" dominantBaseline="middle" className="fill-muted-foreground" fontSize={r * 0.7} fontWeight={600}>
                      {initials}
                    </text>
                  </>
                )}
                <text x={x} y={y + r + 14} textAnchor="middle" className="fill-foreground" fontSize={12} fontWeight={500}>
                  {node.display_name.length > 22 ? `${node.display_name.slice(0, 21)}…` : node.display_name}
                </text>
              </g>
            );
          })}
        </svg>
        <div className="absolute top-2 right-2 flex flex-col gap-1">
          <button
            type="button"
            title="Zoom in"
            aria-label="Zoom in"
            className="h-8 w-8 flex items-center justify-center rounded-md border border-border bg-card/90 hover:bg-muted text-foreground disabled:opacity-40"
            disabled={view.w <= MIN_VIEW_W + 0.5}
            onClick={() => zoomBy(1 / 1.4)}
          >
            <ZoomIn className="h-4 w-4" />
          </button>
          <button
            type="button"
            title="Zoom out"
            aria-label="Zoom out"
            className="h-8 w-8 flex items-center justify-center rounded-md border border-border bg-card/90 hover:bg-muted text-foreground disabled:opacity-40"
            disabled={!zoomed}
            onClick={() => zoomBy(1.4)}
          >
            <ZoomOut className="h-4 w-4" />
          </button>
          <button
            type="button"
            title="Reset view"
            aria-label="Reset view"
            className="h-8 w-8 flex items-center justify-center rounded-md border border-border bg-card/90 hover:bg-muted text-foreground disabled:opacity-40"
            disabled={!zoomed}
            onClick={resetView}
          >
            <Maximize2 className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="min-h-[1.5rem] text-sm text-muted-foreground">
        {hovered ? (
          <span>
            <span className="text-foreground font-medium">{nameOf.get(hovered.person_a_id)}</span>
            {" & "}
            <span className="text-foreground font-medium">{nameOf.get(hovered.person_b_id)}</span>
            {" — "}
            {hovered.shared_assets} {hovered.shared_assets === 1 ? "video" : "videos"} together
            {hovered.together_seconds > 0
              ? ` · ${formatTogether(hovered.together_seconds)} on camera at the same time`
              : " · no overlapping on-camera time detected"}
          </span>
        ) : (
          <span>
            Scroll or use the buttons to zoom · drag to pan · line thickness = videos shared · circle size = total videos · hover a line for details · click a person to open their profile
          </span>
        )}
      </div>
    </div>
  );
}
