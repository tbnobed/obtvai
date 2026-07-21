import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useGetCoAppearances } from "@workspace/api-client-react";
import type { CoAppearanceNode, CoAppearancePair } from "@workspace/api-client-react";
import { useLocation } from "wouter";
import { Maximize2, Share2, ZoomIn, ZoomOut } from "lucide-react";

const W = 960;
const H = 620;
const PAD = 60;
const MAX_K = 4;

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
 *  along edges (stronger pairs pull closer), and center gravity.
 *  Positions are scaled up as the node count grows so the world has room —
 *  zooming in spreads people apart while faces stay the same size. */
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

  const ITER = n > 300 ? 150 : 300;
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
  // Give the world more room as the crowd grows: at ~40 people the map is
  // 1:1; beyond that the coordinate space expands with sqrt(n).
  const s = Math.max(1, Math.sqrt(n / 40));
  for (let i = 0; i < n; i++) { px[i] *= s; py[i] *= s; }
  return { px, py, idx, s };
}

const MIN_SHARED_OPTIONS = [1, 2, 3, 5] as const;
const TOP_N_OPTIONS = [25, 50, 100, 250] as const;

export default function CoAppearanceMap() {
  const [namedOnly, setNamedOnly] = useState(true);
  const [minShared, setMinShared] = useState<number>(1);
  const [topN, setTopN] = useState<number | "all">(50);
  const { data, isLoading } = useGetCoAppearances({ named_only: namedOnly, min_shared: minShared });
  const [, navigate] = useLocation();
  const [hoveredPair, setHoveredPair] = useState<number | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const allNodes = useMemo(() => data?.nodes ?? [], [data]);
  const allPairs = useMemo(
    () => [...(data?.pairs ?? [])].sort((a, b) => a.shared_assets - b.shared_assets),
    [data]
  );

  // Most-connected people first; only the top N are drawn so the map stays
  // legible as the library grows into the hundreds or thousands.
  const { nodes, pairs } = useMemo(() => {
    const degree = new Map<string, number>();
    for (const p of allPairs) {
      degree.set(p.person_a_id, (degree.get(p.person_a_id) ?? 0) + p.shared_assets);
      degree.set(p.person_b_id, (degree.get(p.person_b_id) ?? 0) + p.shared_assets);
    }
    const limit = topN === "all" ? Infinity : topN;
    const ranked = [...allNodes].sort(
      (a, b) =>
        (degree.get(b.person_id) ?? 0) - (degree.get(a.person_id) ?? 0) ||
        b.asset_count - a.asset_count
    );
    const visible = ranked.slice(0, limit);
    const visibleIds = new Set(visible.map((n) => n.person_id));
    return {
      nodes: visible,
      pairs: allPairs.filter((p) => visibleIds.has(p.person_a_id) && visibleIds.has(p.person_b_id)),
    };
  }, [allNodes, allPairs, topN]);

  const layout = useMemo(() => computeLayout(nodes, pairs), [nodes, pairs]);

  // View transform: screen = world * k + t. Node/label sizes are drawn in
  // screen units so faces stay the same size at every zoom level.
  const fitK = 1 / layout.s;
  const svgRef = useRef<SVGSVGElement>(null);
  const [viewT, setViewT] = useState({ k: 1, tx: 0, ty: 0 });
  const viewRef = useRef(viewT);
  viewRef.current = viewT;
  const fitKRef = useRef(fitK);
  fitKRef.current = fitK;
  const layoutRef = useRef(layout);
  layoutRef.current = layout;

  // Manual node positions (world coords) after the user drags people around.
  const [overrides, setOverrides] = useState<Record<string, { x: number; y: number }>>({});

  // The map must always fit inside the visible page (no page scroll): measure
  // the space left below the controls and contain-fit the fixed W:H canvas
  // into it, so the svg's pixel box always matches the viewBox aspect ratio
  // (keeps cursor-to-world math exact — no letterboxing).
  const wrapRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ w: number; h: number } | null>(null);
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setBox((prev) =>
        prev && Math.abs(prev.w - r.width) < 1 && Math.abs(prev.h - r.height) < 1
          ? prev
          : { w: r.width, h: r.height }
      );
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [isLoading, nodes.length]);
  const fit = box ? Math.max(0.1, Math.min(box.w / W, box.h / H)) : 0;

  useLayoutEffect(() => {
    setOverrides({});
    setViewT({ k: 1 / layout.s, tx: 0, ty: 0 });
  }, [layout]);

  const didDragRef = useRef(false);
  const panRef = useRef<{ pointerId: number; startX: number; startY: number; tx: number; ty: number } | null>(null);
  const nodeDragRef = useRef<{ pointerId: number; personId: string; startX: number; startY: number; wx: number; wy: number } | null>(null);
  const [, forceCursor] = useState(0);

  const clampT = (k: number, tx: number, ty: number) => {
    const s = layoutRef.current.s;
    const atFit = k <= fitKRef.current * 1.01;
    const mx = atFit ? 0 : W * 0.6;
    const my = atFit ? 0 : H * 0.6;
    return {
      k,
      tx: Math.min(mx, Math.max(W - W * s * k - mx, tx)),
      ty: Math.min(my, Math.max(H - H * s * k - my, ty)),
    };
  };

  const zoomBy = (factor: number, cx = W / 2, cy = H / 2) =>
    setViewT((v) => {
      const k = Math.min(MAX_K, Math.max(fitKRef.current, v.k * factor));
      const ratio = k / v.k;
      return clampT(k, cx - (cx - v.tx) * ratio, cy - (cy - v.ty) * ratio);
    });

  const resetView = () => setViewT({ k: fitKRef.current, tx: 0, ty: 0 });

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cx = ((e.clientX - rect.left) / rect.width) * W;
      const cy = ((e.clientY - rect.top) / rect.height) * H;
      zoomBy(e.deltaY > 0 ? 1 / 1.25 : 1.25, cx, cy);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, nodes.length]);

  const screenPerPx = () => {
    const rect = svgRef.current?.getBoundingClientRect();
    return rect ? W / rect.width : 1;
  };

  const worldPos = (personId: string): { x: number; y: number } | null => {
    const o = overrides[personId];
    if (o) return o;
    const i = layout.idx.get(personId);
    if (i === undefined) return null;
    return { x: layout.px[i], y: layout.py[i] };
  };

  const onBgPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    didDragRef.current = false;
    panRef.current = { pointerId: e.pointerId, startX: e.clientX, startY: e.clientY, tx: viewT.tx, ty: viewT.ty };
    e.currentTarget.setPointerCapture(e.pointerId);
    forceCursor((c) => c + 1);
  };
  const onBgPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const pan = panRef.current;
    if (!pan || pan.pointerId !== e.pointerId) return;
    const f = screenPerPx();
    const dx = (e.clientX - pan.startX) * f;
    const dy = (e.clientY - pan.startY) * f;
    if (Math.abs(dx) + Math.abs(dy) > 4) didDragRef.current = true;
    setViewT((v) => clampT(v.k, pan.tx + dx, pan.ty + dy));
  };
  const onBgPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    if (panRef.current?.pointerId === e.pointerId) {
      panRef.current = null;
      forceCursor((c) => c + 1);
    }
  };

  const onNodePointerDown = (e: React.PointerEvent<SVGGElement>, personId: string) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    const w = worldPos(personId);
    if (!w) return;
    didDragRef.current = false;
    nodeDragRef.current = { pointerId: e.pointerId, personId, startX: e.clientX, startY: e.clientY, wx: w.x, wy: w.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onNodePointerMove = (e: React.PointerEvent<SVGGElement>) => {
    const drag = nodeDragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const f = screenPerPx() / viewRef.current.k;
    const dx = (e.clientX - drag.startX) * f;
    const dy = (e.clientY - drag.startY) * f;
    if (Math.abs(e.clientX - drag.startX) + Math.abs(e.clientY - drag.startY) > 4) didDragRef.current = true;
    setOverrides((o) => ({ ...o, [drag.personId]: { x: drag.wx + dx, y: drag.wy + dy } }));
  };
  const onNodePointerUp = (e: React.PointerEvent<SVGGElement>) => {
    if (nodeDragRef.current?.pointerId === e.pointerId) nodeDragRef.current = null;
  };

  const nameOf = useMemo(() => new Map(allNodes.map((n) => [n.person_id, n.display_name])), [allNodes]);
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
  const { k, tx, ty } = viewT;
  const zoomedIn = k > fitK * 1.01;
  const showAllLabels = nodes.length <= 80 || k >= fitK * 1.8;

  // When zoomed in, people connected to someone on screen shouldn't vanish
  // off the edge — pull them to the border of the view (in the direction of
  // their true position) so their connection lines stay visible.
  const displayPos = useMemo(() => {
    const map = new Map<string, { x: number; y: number; pulled: boolean }>();
    const raw = new Map<string, { x: number; y: number }>();
    const onScreen = new Set<string>();
    for (const node of nodes) {
      const w = worldPos(node.person_id);
      if (!w) continue;
      const x = w.x * k + tx;
      const y = w.y * k + ty;
      raw.set(node.person_id, { x, y });
      const r = nodeRadius(node.asset_count, maxAssets);
      if (x >= -r && x <= W + r && y >= -r && y <= H + r) onScreen.add(node.person_id);
    }
    const linkedToVisible = new Set<string>();
    if (zoomedIn) {
      for (const p of pairs) {
        if (onScreen.has(p.person_a_id) && !onScreen.has(p.person_b_id)) linkedToVisible.add(p.person_b_id);
        if (onScreen.has(p.person_b_id) && !onScreen.has(p.person_a_id)) linkedToVisible.add(p.person_a_id);
      }
    }
    for (const node of nodes) {
      const pos = raw.get(node.person_id);
      if (!pos) continue;
      if (onScreen.has(node.person_id) || !linkedToVisible.has(node.person_id)) {
        map.set(node.person_id, { ...pos, pulled: false });
      } else {
        const r = nodeRadius(node.asset_count, maxAssets);
        const m = r + 8;
        map.set(node.person_id, {
          x: Math.min(W - m, Math.max(m, pos.x)),
          y: Math.min(H - m, Math.max(m, pos.y)),
          pulled: true,
        });
      }
    }
    return map;
    // worldPos depends on overrides + layout, both listed below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, pairs, k, tx, ty, zoomedIn, overrides, layout, maxAssets]);

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
      <label className="flex items-center gap-2">
        <span className="text-muted-foreground">Show</span>
        <select
          value={topN === "all" ? "all" : String(topN)}
          onChange={(e) => setTopN(e.target.value === "all" ? "all" : Number(e.target.value))}
          className="bg-card border border-border rounded px-2 py-1 text-sm"
        >
          {TOP_N_OPTIONS.map((n) => (
            <option key={n} value={n}>Top {n}</option>
          ))}
          <option value="all">Everyone</option>
        </select>
      </label>
      {!isLoading && (
        <span className="text-xs text-muted-foreground ml-auto">
          {nodes.length < allNodes.length
            ? `${nodes.length} of ${allNodes.length} people (most connected) · ${pairs.length} ${pairs.length === 1 ? "connection" : "connections"}`
            : `${nodes.length} ${nodes.length === 1 ? "person" : "people"} · ${pairs.length} ${pairs.length === 1 ? "connection" : "connections"}`}
        </span>
      )}
    </div>
  );

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3 flex-1 min-h-0">
        {controls}
        <div className="animate-pulse bg-muted rounded-md w-full flex-1 min-h-0" />
      </div>
    );
  }

  if (!nodes.length) {
    return (
      <div className="flex flex-col gap-3 flex-1 min-h-0">
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
    <div className="flex flex-col gap-3 flex-1 min-h-0">
      {controls}
      <div ref={wrapRef} className="flex-1 min-h-0 flex items-start justify-center">
      <div
        className="relative border border-border bg-card rounded-md overflow-hidden"
        style={
          box
            ? { width: Math.max(1, Math.floor(W * fit)), height: Math.max(1, Math.floor(H * fit)) }
            : { width: "100%", aspectRatio: `${W}/${H}`, visibility: "hidden" as const }
        }
      >
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="w-full h-full block touch-none select-none"
          style={{ cursor: panRef.current ? "grabbing" : "grab" }}
          role="img"
          aria-label="Co-appearance map"
          onPointerDown={onBgPointerDown}
          onPointerMove={onBgPointerMove}
          onPointerUp={onBgPointerUp}
          onPointerCancel={onBgPointerUp}
        >
          {pairs.map((p, i) => {
            const pa = displayPos.get(p.person_a_id);
            const pb = displayPos.get(p.person_b_id);
            if (!pa || !pb) return null;
            const strong = hoveredPair === i;
            const dimmed =
              (hoveredPair !== null && !strong) ||
              (connectedTo !== null && !(connectedTo.has(p.person_a_id) && connectedTo.has(p.person_b_id) && (p.person_a_id === hoveredNode || p.person_b_id === hoveredNode)));
            return (
              <line
                key={i}
                x1={pa.x} y1={pa.y}
                x2={pb.x} y2={pb.y}
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
            const p = displayPos.get(node.person_id);
            if (!p) return null;
            const { x, y, pulled } = p;
            const r = nodeRadius(node.asset_count, maxAssets);
            if (!pulled && (x < -r * 2 || x > W + r * 2 || y < -r * 2 || y > H + r * 2)) return null;
            const inHoveredPair =
              hovered !== null && (hovered.person_a_id === node.person_id || hovered.person_b_id === node.person_id);
            const dimmed =
              (connectedTo !== null && !connectedTo.has(node.person_id)) ||
              (hovered !== null && !inHoveredPair);
            const showLabel =
              showAllLabels ||
              hoveredNode === node.person_id ||
              (connectedTo?.has(node.person_id) ?? false) ||
              inHoveredPair;
            const initials = node.display_name
              .split(/\s+/)
              .map((w2) => w2[0])
              .filter(Boolean)
              .slice(0, 2)
              .join("")
              .toUpperCase();
            return (
              <g
                key={node.person_id}
                style={{ cursor: "grab", opacity: dimmed ? 0.3 : pulled ? 0.75 : 1, transition: "opacity 120ms" }}
                onClick={() => {
                  if (didDragRef.current) return;
                  navigate(`/people/${node.person_id}`);
                }}
                onPointerDown={(e) => onNodePointerDown(e, node.person_id)}
                onPointerMove={onNodePointerMove}
                onPointerUp={onNodePointerUp}
                onPointerCancel={onNodePointerUp}
                onMouseEnter={() => setHoveredNode(node.person_id)}
                onMouseLeave={() => setHoveredNode(null)}
              >
                <title>{`${node.display_name} — ${node.asset_count} ${node.asset_count === 1 ? "video" : "videos"} · drag to move, click to open`}</title>
                <circle
                  cx={x} cy={y} r={r + 2}
                  className="fill-card stroke-primary/60"
                  strokeWidth={hoveredNode === node.person_id || inHoveredPair ? 2.5 : 1}
                  strokeDasharray={pulled ? "4 3" : undefined}
                />
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
                {showLabel && (
                  <text x={x} y={y + r + 14} textAnchor="middle" className="fill-foreground" fontSize={12} fontWeight={500}>
                    {node.display_name.length > 22 ? `${node.display_name.slice(0, 21)}…` : node.display_name}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
        <div className="absolute top-2 right-2 flex flex-col gap-1">
          <button
            type="button"
            title="Zoom in (spread people apart)"
            aria-label="Zoom in"
            className="h-8 w-8 flex items-center justify-center rounded-md border border-border bg-card/90 hover:bg-muted text-foreground disabled:opacity-40"
            disabled={k >= MAX_K - 0.01}
            onClick={() => zoomBy(1.4)}
          >
            <ZoomIn className="h-4 w-4" />
          </button>
          <button
            type="button"
            title="Zoom out"
            aria-label="Zoom out"
            className="h-8 w-8 flex items-center justify-center rounded-md border border-border bg-card/90 hover:bg-muted text-foreground disabled:opacity-40"
            disabled={!zoomedIn}
            onClick={() => zoomBy(1 / 1.4)}
          >
            <ZoomOut className="h-4 w-4" />
          </button>
          <button
            type="button"
            title="Reset view"
            aria-label="Reset view"
            className="h-8 w-8 flex items-center justify-center rounded-md border border-border bg-card/90 hover:bg-muted text-foreground disabled:opacity-40"
            disabled={!zoomedIn && Object.keys(overrides).length === 0}
            onClick={() => {
              resetView();
              setOverrides({});
            }}
          >
            <Maximize2 className="h-4 w-4" />
          </button>
        </div>
      </div>
      </div>
      <div className="min-h-[1.5rem] text-sm text-muted-foreground shrink-0">
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
            Scroll to zoom (spreads people apart) · drag the background to pan · drag a person to move them · click a person to open their profile · line thickness = videos shared
          </span>
        )}
      </div>
    </div>
  );
}
