import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearch } from "wouter";
import {
  useListProjects,
  getListProjectsQueryKey,
  useCreateProject,
  useUpdateProject,
  useSemanticSearch,
  useGetSearchHistory,
  getGetSearchHistoryQueryKey,
  useListSavedSearches,
  getListSavedSearchesQueryKey,
  useCreateSavedSearch,
  useDeleteSavedSearch,
  useListEmotionFacets,
  getListEmotionFacetsQueryKey,
  useListEmotionMoments,
  getListEmotionMomentsQueryKey,
  useBackfillSentiment,
} from "@workspace/api-client-react";
import type { SearchResult } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Search, Play, Loader2, ExternalLink, History, Bookmark, BookmarkPlus, X, HeartPulse, Check, FolderKanban, Plus } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ClipPlayerDialog, type PlayerClip } from "@/components/project/clip-player-dialog";
import { formatTC } from "@/lib/timecode";

type SearchScope = "combined" | "transcript" | "visual";

const EMOTION_COLORS: Record<string, string> = {
  joy: "#facc15",
  humor: "#fb923c",
  excitement: "#f97316",
  warmth: "#4ade80",
  pride: "#34d399",
  surprise: "#a78bfa",
  sadness: "#60a5fa",
  anger: "#f87171",
  tension: "#ef4444",
  fear: "#c084fc",
};

const SCOPES: { value: SearchScope; label: string }[] = [
  { value: "combined", label: "All" },
  { value: "transcript", label: "Transcript" },
  { value: "visual", label: "Visuals" },
];

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<SearchScope>("combined");
  const [playerClip, setPlayerClip] = useState<PlayerClip | null>(null);
  const searchMutation = useSemanticSearch();
  const { data: history } = useGetSearchHistory({
    query: { queryKey: getGetSearchHistoryQueryKey() },
  });
  const queryClient = useQueryClient();
  const { data: savedSearches } = useListSavedSearches({
    query: { queryKey: getListSavedSearchesQueryKey() },
  });
  const createSaved = useCreateSavedSearch();
  const deleteSaved = useDeleteSavedSearch();
  const invalidateSaved = () =>
    queryClient.invalidateQueries({ queryKey: getListSavedSearchesQueryKey() });
  const alreadySaved = savedSearches?.some(
    (sv) => sv.query.trim().toLowerCase() === query.trim().toLowerCase() && sv.search_type === scope,
  );

  const [emotion, setEmotion] = useState<string | null>(null);
  const { data: emotionFacets } = useListEmotionFacets({
    query: { queryKey: getListEmotionFacetsQueryKey() },
  });
  const emotionParams = { emotion: emotion ?? "", limit: 100 };
  const { data: emotionMoments, isLoading: emotionLoading } = useListEmotionMoments(
    emotionParams,
    { query: { queryKey: getListEmotionMomentsQueryKey(emotionParams), enabled: !!emotion } },
  );
  const backfillSentiment = useBackfillSentiment();

  // ---- Select results → add to / create a project ----
  const { data: projects } = useListProjects();
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const [selected, setSelected] = useState<Record<string, SearchResult>>({});
  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [addedTo, setAddedTo] = useState<{ id: string; name: string } | null>(null);
  const selectedList = Object.values(selected);
  const selectedMediaIds = [...new Set(selectedList.map((r) => r.media_id))];
  const activeProjects = (projects ?? []).filter((p) => p.status === "active");
  const projectBusy = createProject.isPending || updateProject.isPending;

  const toggleSelected = (key: string, r: SearchResult) =>
    setSelected((cur) => {
      const next = { ...cur };
      if (next[key]) delete next[key];
      else next[key] = r;
      return next;
    });

  const addToProject = (projectId: string, projectName: string) => {
    const existing = (projects ?? []).find((p) => p.id === projectId);
    const merged = [...new Set([...(existing?.media_ids ?? []), ...selectedMediaIds])];
    updateProject.mutate(
      { id: projectId, data: { media_ids: merged } },
      {
        onSuccess: () => {
          queryClient.invalidateQueries({ queryKey: getListProjectsQueryKey() });
          setSelected({});
          setAddedTo({ id: projectId, name: projectName });
        },
      },
    );
  };

  const createProjectWithSelection = () => {
    if (!newProjectName.trim()) return;
    createProject.mutate(
      { data: { name: newProjectName.trim(), media_ids: selectedMediaIds } },
      {
        onSuccess: (p) => {
          queryClient.invalidateQueries({ queryKey: getListProjectsQueryKey() });
          setSelected({});
          setNewProjectOpen(false);
          setNewProjectName("");
          navigate(`/studio/${p.id}`);
        },
      },
    );
  };

  const runSearch = (q?: string, s?: SearchScope) => {
    const term = (q ?? query).trim();
    if (term.length < 2) return;
    if (q) setQuery(q);
    // Record the search in the URL so back/forward restores it instead of
    // dropping you on an empty page.
    const effScope = s ?? scope;
    const url = `/search?q=${encodeURIComponent(term)}${effScope !== "combined" ? `&scope=${effScope}` : ""}`;
    if (window.location.search !== url.slice(url.indexOf("?"))) navigate(url);
    setSelected({});
    setAddedTo(null);
    searchMutation.mutate(
      { data: { query: term, search_type: effScope, limit: 500 } },
      {
        onSuccess: () =>
          queryClient.invalidateQueries({ queryKey: getGetSearchHistoryQueryKey() }),
      },
    );
  };

  // Support /search?q=… deep links (Dashboard search box, browser
  // back/forward). Re-runs whenever the URL's query changes, so history
  // navigation restores the results you were looking at.
  const searchString = useSearch();
  const [, navigate] = useLocation();
  const lastUrlQuery = useRef<string | null>(null);
  useEffect(() => {
    const p = new URLSearchParams(searchString);
    const q = p.get("q");
    const s = (p.get("scope") as SearchScope | null) ?? "combined";
    const key = q ? `${q}|${s}` : null;
    if (key && key !== lastUrlQuery.current && q!.trim().length >= 2) {
      lastUrlQuery.current = key;
      setScope(s);
      runSearch(q!, s);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchString]);

  const resultCard = (r: SearchResult, key: string) => {
    const isSelected = !!selected[key];
    return (
    <div key={key} className={`bg-muted/50 rounded overflow-hidden text-sm flex flex-col relative ${isSelected ? "ring-2 ring-primary" : ""}`}>
      <button
        type="button"
        aria-label={isSelected ? "Deselect this result" : "Select this result"}
        title={isSelected ? "Deselect" : "Select to add to a project"}
        onClick={() => toggleSelected(key, r)}
        className={`absolute top-1.5 left-1.5 z-10 h-6 w-6 rounded-md border flex items-center justify-center transition-colors ${
          isSelected
            ? "bg-primary border-primary text-primary-foreground"
            : "bg-black/60 border-white/40 text-transparent hover:border-white hover:text-white/60"
        }`}
      >
        <Check className="h-4 w-4" />
      </button>
      <button
        type="button"
        className="relative w-full aspect-video bg-black/40 flex items-center justify-center cursor-pointer group"
        title="Play this clip"
        onClick={() =>
          setPlayerClip({
            media_id: r.media_id,
            start_time: r.start_time,
            end_time: r.end_time,
            label: r.snippet || undefined,
            filename: r.filename,
          })
        }
      >
        {r.thumbnail_url ? (
          <img
            src={`/api/thumbnails/${r.thumbnail_url}`}
            alt=""
            loading="lazy"
            className="w-full h-full object-cover"
          />
        ) : (
          <Play className="h-6 w-6 text-muted-foreground" />
        )}
        <span className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/40 transition-colors">
          <Play className="h-6 w-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
        </span>
        <span className="absolute bottom-1 right-1 text-[10px] px-1 py-0.5 rounded bg-black/70 text-white">
          {formatTC(r.start_time, 25, false)}–{formatTC(r.end_time, 25, false)}
        </span>
      </button>
      <div className="p-2.5 flex-1 flex flex-col gap-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div className="truncate font-medium">{r.filename}</div>
          <Button asChild size="icon" variant="ghost" className="h-6 w-6 shrink-0 -mt-0.5" title="Open the asset at this timecode">
            <Link href={`/library/${r.media_id}?t=${Math.floor(r.start_time)}`}>
              <ExternalLink className="h-3.5 w-3.5" />
            </Link>
          </Button>
        </div>
        <div className="text-xs text-muted-foreground">
          {r.match_type === "person" ? "Person match" : r.match_type === "visual" ? "Visual match" : "Transcript match"}{r.match_type === "person" ? "" : ` · ${(r.score * 100).toFixed(0)}%`}
        </div>
        {r.snippet && (
          <div className="text-xs text-muted-foreground line-clamp-2">“{r.snippet}”</div>
        )}
      </div>
    </div>
    );
  };

  const hasResults = !!searchMutation.data;

  return (
    <div className="h-full overflow-y-auto">
      {/* ---- Hero search ------------------------------------------------ */}
      <div className="relative border-b border-border overflow-hidden">
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            backgroundImage:
              "radial-gradient(circle at 25% 0%, hsl(var(--primary) / 0.22), transparent 45%), radial-gradient(circle at 75% 10%, hsl(280 80% 60% / 0.13), transparent 40%)",
          }}
        />
        <div className={`relative max-w-4xl mx-auto px-6 text-center transition-all ${hasResults ? "pt-5 pb-4" : "pt-12 pb-8"}`}>
          {!hasResults && (
            <>
              <h1 className="text-3xl font-bold tracking-tight">Search every word and frame</h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Natural-language search across transcripts, visuals, and people — not just filenames.
              </p>
            </>
          )}
          <div className={`relative max-w-3xl mx-auto ${hasResults ? "" : "mt-5"}`}>
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground pointer-events-none" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder='Try "mayor talks about the housing vote" or "crowd outside city hall at night"'
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
              autoFocus
              className="w-full h-12 pl-12 pr-36 rounded-xl bg-card border border-border text-base shadow-lg focus:outline-none focus:ring-2 focus:ring-primary/60 placeholder:text-muted-foreground/70 transition-shadow"
              data-testid="input-search"
            />
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1.5">
              <Button
                size="icon"
                variant="ghost"
                className="h-9 w-9"
                title={alreadySaved ? "Already saved" : "Save this search — it re-runs live, so it grows as new footage is indexed"}
                disabled={query.trim().length < 2 || !!alreadySaved || createSaved.isPending}
                onClick={() =>
                  createSaved.mutate(
                    { data: { name: query.trim(), query: query.trim(), search_type: scope } },
                    { onSuccess: invalidateSaved },
                  )
                }
              >
                <BookmarkPlus className="h-4 w-4" />
              </Button>
              <Button className="h-9" onClick={() => runSearch()} disabled={query.trim().length < 2 || searchMutation.isPending}>
                {searchMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
              </Button>
            </div>
          </div>
          <div className="mt-3 flex items-center justify-center gap-1">
            {SCOPES.map((s) => (
              <Button
                key={s.value}
                size="sm"
                variant={scope === s.value ? "secondary" : "ghost"}
                className="h-7 px-3.5 text-xs rounded-full"
                onClick={() => {
                  setScope(s.value);
                  if (query.trim().length >= 2) runSearch(undefined, s.value);
                }}
              >
                {s.label}
              </Button>
            ))}
          </div>
        </div>
      </div>

      <div className="p-6 space-y-5 w-full">
      {!!savedSearches?.length && (
        <div className="flex items-center justify-center gap-2 flex-wrap">
          <Bookmark className="h-3.5 w-3.5 text-primary" />
          <span className="text-xs text-muted-foreground">Saved searches:</span>
          {savedSearches.map((sv) => (
            <Badge
              key={sv.id}
              variant="outline"
              className="cursor-pointer hover:bg-muted border-primary/40 pl-2.5 pr-1 gap-1 group/chip"
              onClick={() => {
                setScope(sv.search_type as SearchScope);
                runSearch(sv.query, sv.search_type as SearchScope);
              }}
            >
              {sv.name}
              <button
                type="button"
                className="rounded-full p-0.5 hover:bg-destructive/20 hover:text-destructive opacity-40 group-hover/chip:opacity-100 transition-opacity"
                title="Remove saved search"
                onClick={(e) => {
                  e.stopPropagation();
                  deleteSaved.mutate({ savedId: sv.id }, { onSuccess: invalidateSaved });
                }}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      <div className="flex items-center justify-center gap-2 flex-wrap">
        <HeartPulse className="h-3.5 w-3.5 text-primary" />
        <span className="text-xs text-muted-foreground">Emotions:</span>
        {emotionFacets?.length ? (
          emotionFacets.map((f) => (
            <Badge
              key={f.emotion}
              variant={emotion === f.emotion ? "secondary" : "outline"}
              className="cursor-pointer hover:bg-muted"
              style={{ borderColor: `${EMOTION_COLORS[f.emotion] ?? "#71717a"}66`, color: emotion === f.emotion ? undefined : EMOTION_COLORS[f.emotion] }}
              onClick={() => setEmotion((cur) => (cur === f.emotion ? null : f.emotion))}
            >
              {f.emotion} · {f.count}
            </Badge>
          ))
        ) : (
          <>
            <span className="text-xs text-muted-foreground">none scored yet</span>
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 text-xs"
              disabled={backfillSentiment.isPending || backfillSentiment.isSuccess}
              onClick={() => backfillSentiment.mutate(undefined as never, {
                onSuccess: () => queryClient.invalidateQueries({ queryKey: getListEmotionFacetsQueryKey() }),
              })}
              title="Score every existing transcript for sentiment & emotion (runs in the background on the worker)"
            >
              {backfillSentiment.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : backfillSentiment.isSuccess ? "Queued — check back after processing" : "Analyze emotions across library"}
            </Button>
          </>
        )}
      </div>

      {emotion && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-sm capitalize" style={{ color: EMOTION_COLORS[emotion] }}>
              {emotionLoading ? "Loading…" : `${emotionMoments?.items.length ?? 0} ${emotion} moment${(emotionMoments?.items.length ?? 0) === 1 ? "" : "s"} across the library`}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {emotionMoments?.items.length ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3">
                {emotionMoments.items.map((m, i) => (
                  <button
                    key={`${m.media_id}-${m.start_time}-${i}`}
                    type="button"
                    className="bg-muted/50 rounded overflow-hidden text-sm flex flex-col text-left group cursor-pointer hover:ring-1 hover:ring-primary/50 transition-shadow"
                    onClick={() =>
                      setPlayerClip({
                        media_id: m.media_id,
                        start_time: m.start_time,
                        end_time: m.end_time,
                        label: m.text,
                        filename: m.filename,
                      })
                    }
                  >
                    <div className="relative w-full aspect-video bg-black/40 flex items-center justify-center">
                      {m.thumbnail_url ? (
                        <img
                          src={`/api/thumbnails/${m.thumbnail_url}`}
                          alt=""
                          loading="lazy"
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <Play className="h-6 w-6 text-muted-foreground" />
                      )}
                      <span className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/40 transition-colors">
                        <Play className="h-6 w-6 text-white opacity-0 group-hover:opacity-100 transition-opacity" />
                      </span>
                      <span className="absolute bottom-1 left-1 text-[10px] px-1 py-0.5 rounded bg-black/70 text-white font-mono">
                        {formatTC(m.start_time, 25, false)}
                      </span>
                      {m.sentiment != null && (
                        <span
                          className="absolute bottom-1 right-1 text-[10px] px-1 py-0.5 rounded bg-black/70 font-mono"
                          style={{ color: EMOTION_COLORS[emotion] ?? "#fff" }}
                        >
                          {m.sentiment > 0 ? "+" : ""}{m.sentiment.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <div className="p-2.5 flex-1 flex flex-col gap-1 min-w-0 w-full">
                      <div className="truncate font-medium text-xs w-full">{m.filename}</div>
                      <p className="text-xs text-muted-foreground line-clamp-2">
                        {m.speaker ? `${m.speaker}: ` : ""}“{m.text}”
                      </p>
                    </div>
                  </button>
                ))}
              </div>
            ) : emotionLoading ? null : (
              <p className="text-sm text-muted-foreground">No moments carry this emotion.</p>
            )}
          </CardContent>
        </Card>
      )}

      {!searchMutation.data && !searchMutation.isPending && !!history?.length && (
        <div className="flex items-center justify-center gap-2 flex-wrap">
          <History className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">Recent:</span>
          {history.slice(0, 8).map((h) => (
            <Badge
              key={h.id}
              variant="outline"
              className="cursor-pointer hover:bg-muted"
              onClick={() => runSearch(h.query)}
            >
              {h.query}
            </Badge>
          ))}
        </div>
      )}

      {searchMutation.isError && (
        <p className="text-sm text-red-400">Search failed — try again.</p>
      )}

      {addedTo && (
        <p className="text-sm text-emerald-400 text-center">
          Added to <Link href={`/studio/${addedTo.id}`} className="underline underline-offset-2 hover:text-emerald-300">{addedTo.name}</Link>.
        </p>
      )}

      {searchMutation.data && (
        <Card>
          <CardHeader className="py-3 flex flex-row items-center justify-between space-y-0 flex-wrap gap-2">
            <CardTitle className="text-sm">
              {searchMutation.data.results.length} result{searchMutation.data.results.length === 1 ? "" : "s"} for “{searchMutation.data.query}”
            </CardTitle>
            <span className="text-xs text-muted-foreground">
              Tick results to add them to a project
            </span>
          </CardHeader>
          <CardContent>
            {searchMutation.data.results.length ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-3">
                {searchMutation.data.results.map((r, i) => resultCard(r, `s-${i}`))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No matches. Try different wording — the search is semantic, not keyword-based.</p>
            )}
          </CardContent>
        </Card>
      )}

      {selectedList.length > 0 && (
        <div className="sticky bottom-4 z-20 flex justify-center">
          <div className="flex items-center gap-3 rounded-xl border border-border bg-card/95 backdrop-blur px-4 py-2.5 shadow-xl">
            <span className="text-sm">
              <span className="font-semibold">{selectedList.length}</span> clip{selectedList.length === 1 ? "" : "s"} ·{" "}
              <span className="font-semibold">{selectedMediaIds.length}</span> file{selectedMediaIds.length === 1 ? "" : "s"}
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="outline" disabled={projectBusy || !activeProjects.length}
                  title={activeProjects.length ? "Add the selected files to an existing project" : "No active projects yet"}>
                  {updateProject.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <FolderKanban className="h-4 w-4 mr-2" />}
                  Add to project
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="center" className="max-h-72 overflow-y-auto">
                {activeProjects.map((p) => (
                  <DropdownMenuItem key={p.id} onClick={() => addToProject(p.id, p.name)}>
                    {p.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <Button size="sm" disabled={projectBusy} onClick={() => { setNewProjectName(query.trim() || ""); setNewProjectOpen(true); }}>
              <Plus className="h-4 w-4 mr-2" /> New project
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected({})}>
              Clear
            </Button>
          </div>
        </div>
      )}

      <Dialog open={newProjectOpen} onOpenChange={(o) => !projectBusy && setNewProjectOpen(o)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>New project from selection</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Input
              value={newProjectName}
              onChange={(e) => setNewProjectName(e.target.value)}
              placeholder="Project name"
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && createProjectWithSelection()}
            />
            <p className="text-xs text-muted-foreground">
              Starts the project with the {selectedMediaIds.length} source file{selectedMediaIds.length === 1 ? "" : "s"} behind your selected clips.
            </p>
            {createProject.isError && (
              <p className="text-xs text-red-400">Couldn't create the project — try again.</p>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setNewProjectOpen(false)} disabled={projectBusy}>Cancel</Button>
            <Button onClick={createProjectWithSelection} disabled={!newProjectName.trim() || projectBusy}>
              {createProject.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
              Create project
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ClipPlayerDialog clip={playerClip} onClose={() => setPlayerClip(null)} />
    </div>
    </div>
  );
}
