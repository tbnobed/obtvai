import { useEffect, useRef, useState } from "react";
import {
  useListPeople,
  useReanalyzePeople,
  useUpdatePerson,
  useDeletePerson,
  getListPeopleQueryKey,
} from "@workspace/api-client-react";
import { Link } from "wouter";
import {
  Users,
  User,
  Mic,
  Film,
  ScanFace,
  Pencil,
  Check,
  X,
  ChevronLeft,
  ChevronRight,
  Trash2,
  LayoutGrid,
  List,
  Share2,
  Search,
  ArrowDownAZ,
  TrendingUp,
  BadgeCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { useQueryClient } from "@tanstack/react-query";
import CoAppearanceMap from "@/components/co-appearance-map";
import EnrollPersonDialog from "@/components/enroll-person-dialog";

function formatSpeaking(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(0);
  const started = useRef<number | null>(null);
  useEffect(() => {
    let raf = 0;
    started.current = null;
    const step = (t: number) => {
      if (started.current === null) started.current = t;
      const p = Math.min(1, (t - started.current) / duration);
      setValue(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return value;
}

// Divisible by every grid column count (3, 4, 5, 6, 8, 10) so a full page
// always ends on a complete row — no dangling empty cells.
const PAGE_SIZE = 120;

export default function People() {
  const [view, setView] = useState<"grid" | "list" | "map">(() => {
    const v = new URLSearchParams(window.location.search).get("view");
    if (v === "map" || v === "list" || v === "grid") return v as "grid" | "list" | "map";
    return (localStorage.getItem("people-view") as "grid" | "list" | "map") || "grid";
  });
  
  const switchView = (v: "grid" | "list" | "map") => {
    setView(v);
    if (v !== "map") localStorage.setItem("people-view", v);
  };
  
  const [page, setPage] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"appearances" | "name">("appearances");
  const [facesOnly, setFacesOnly] = useState<boolean>(
    () => localStorage.getItem("people-faces-only") !== "false"
  );
  
  const [namedOnly, setNamedOnly] = useState<boolean>(
    () => localStorage.getItem("people-named-only") === "true"
  );

  const toggleNamedOnly = () => {
    setNamedOnly((v) => {
      localStorage.setItem("people-named-only", String(!v));
      return !v;
    });
    setPage(0);
  };

  const toggleFacesOnly = () => {
    setFacesOnly((v) => {
      localStorage.setItem("people-faces-only", String(!v));
      return !v;
    });
    setPage(0);
  };

  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(searchInput.trim());
      setPage(0);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const { data, isLoading } = useListPeople({
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    ...(query ? { q: query } : {}),
    sort,
    ...(facesOnly ? { faces_only: true } : {}),
    ...(namedOnly ? { named_only: true } : {}),
  });
  
  const people = data?.items;
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const animTotal = useCountUp(total);

  useEffect(() => {
    if (data && page > 0 && page > totalPages - 1) {
      setPage(totalPages - 1);
    }
  }, [data, page, totalPages]);

  const reanalyzeMutation = useReanalyzePeople();
  const updatePerson = useUpdatePerson();
  const deletePerson = useDeletePerson();
  const queryClient = useQueryClient();
  const [queuedMessage, setQueuedMessage] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");

  const startEdit = (e: React.MouseEvent, id: string, currentName: string) => {
    e.preventDefault();
    e.stopPropagation();
    setEditingId(id);
    setEditName(currentName.startsWith("Person ") || currentName.startsWith("SPEAKER_") ? "" : currentName);
  };

  const cancelEdit = (e?: React.SyntheticEvent) => {
    e?.preventDefault();
    e?.stopPropagation();
    setEditingId(null);
    setEditName("");
  };

  const saveEdit = (e: React.SyntheticEvent, id: string) => {
    e.preventDefault();
    e.stopPropagation();
    const name = editName.trim();
    if (!name || updatePerson.isPending) return;
    updatePerson.mutate(
      { id, data: { display_name: name } },
      {
        onSuccess: () => {
          setEditingId(null);
          setEditName("");
          queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
        },
        onError: () => setQueuedMessage("Rename failed — check the API server."),
      }
    );
  };

  const handleDelete = (e: React.MouseEvent, id: string, name: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (deletePerson.isPending) return;
    if (!window.confirm(`Delete "${name}"? This removes the person, their appearances, and any voice-clone data.`)) return;
    deletePerson.mutate(
      { id },
      {
        onSuccess: () => queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() }),
        onError: () => setQueuedMessage("Delete failed — check the API server."),
      }
    );
  };

  const handleReanalyze = () => {
    reanalyzeMutation.mutate(undefined, {
      onSuccess: (result) => {
        setQueuedMessage(
          result.assets_queued > 0
            ? `Queued ${result.jobs_created} analysis jobs across ${result.assets_queued} assets — people will appear as processing completes.`
            : "Nothing to re-analyze — all assets are already queued or processing."
        );
        queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
      },
      onError: () => setQueuedMessage("Re-analysis request failed — check the API server."),
    });
  };

  const maxSpeaking = people && people.length > 0 
    ? Math.max(...people.map((p) => p.total_speaking_seconds ?? 0)) 
    : 1;

  return (
    <div className={view === "map" ? "flex-1 h-full overflow-hidden flex flex-col bg-background" : "flex-1 overflow-y-auto flex flex-col bg-background"}>
      {/* ---- Header (hidden in map view so the map fills the screen) ---- */}
      {view !== "map" && (
      <div className="relative border-b border-border bg-gradient-to-b from-primary/10 via-background to-background overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.35] pointer-events-none"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 0%, hsl(var(--primary) / 0.25), transparent 45%), radial-gradient(circle at 80% 10%, hsl(280 80% 60% / 0.15), transparent 40%)",
          }}
        />
        <div className="relative w-full px-10 pt-14 pb-10 flex flex-col md:flex-row items-end justify-between gap-6">
          <div>
            <h1 className="text-4xl font-bold tracking-tight">People Directory</h1>
            {total > 0 && (
              <p className="mt-3 text-muted-foreground text-lg">
                <span className="text-foreground font-semibold tracking-tight">{Math.round(animTotal)}</span> identities tracked across your library
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              onClick={handleReanalyze}
              disabled={reanalyzeMutation.isPending}
              className="bg-background/50 backdrop-blur-sm border-primary/20 hover:border-primary/50 hover:bg-primary/10 transition-colors"
            >
              <ScanFace className="h-4 w-4 mr-2 text-primary/70" />
              {reanalyzeMutation.isPending ? "Queuing..." : "Re-analyze Library"}
            </Button>
          </div>
        </div>
      </div>
      )}

      <div className={view === "map" ? "p-3 w-full flex flex-col flex-1 overflow-hidden" : "px-10 py-8 w-full flex flex-col flex-1"}>
        {queuedMessage && (
          <div className="mb-6 px-4 py-3 rounded-xl border border-primary/20 bg-primary/5 text-sm text-primary shadow-sm flex items-center gap-3">
            <Check className="h-4 w-4 shrink-0" />
            {queuedMessage}
          </div>
        )}

        <div className="flex flex-col lg:flex-row items-center justify-between gap-4 mb-8">
          {view !== "map" ? (
            <div className="relative w-full lg:w-96">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              <Input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Search people by name..."
                className="h-10 pl-10 pr-10 rounded-full bg-card/50 border-border/50 focus-visible:ring-primary/50 shadow-sm transition-all focus:bg-card"
              />
              {searchInput && (
                <button
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setSearchInput("")}
                  title="Clear search"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          ) : (
            <div className="relative w-full lg:w-96" />
          )}
          
          <div className="flex flex-wrap items-center gap-3 w-full lg:w-auto justify-start lg:justify-end">
            {view !== "map" && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-10 rounded-full px-4 gap-2 bg-card/50 border-border/50 shadow-sm"
                  onClick={() => {
                    setSort((s) => (s === "name" ? "appearances" : "name"));
                    setPage(0);
                  }}
                  title="Toggle sort order"
                >
                  {sort === "name" ? (
                    <><ArrowDownAZ className="h-4 w-4 text-primary/70" /> Name A–Z</>
                  ) : (
                    <><TrendingUp className="h-4 w-4 text-primary/70" /> Most seen</>
                  )}
                </Button>
                <Button
                  size="sm"
                  variant={facesOnly ? "secondary" : "outline"}
                  className={`h-10 rounded-full px-4 gap-2 shadow-sm transition-colors ${
                    facesOnly 
                      ? "bg-primary/15 text-primary border-primary/30 hover:bg-primary/25" 
                      : "bg-card/50 border-border/50 hover:bg-card"
                  }`}
                  onClick={toggleFacesOnly}
                  title={facesOnly ? "Showing only people with a detected face — click to include voice-only speakers" : "Including voice-only speakers (off-camera voices) — click to hide them"}
                >
                  {facesOnly ? <ScanFace className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                  {facesOnly ? "Faces only" : "All speakers"}
                </Button>
                <Button
                  size="sm"
                  variant={namedOnly ? "secondary" : "outline"}
                  className={`h-10 rounded-full px-4 gap-2 shadow-sm transition-colors ${
                    namedOnly
                      ? "bg-primary/15 text-primary border-primary/30 hover:bg-primary/25"
                      : "bg-card/50 border-border/50 hover:bg-card"
                  }`}
                  onClick={toggleNamedOnly}
                  title={namedOnly ? 'Showing only identified people — click to include "Person N" and speaker placeholders' : 'Including unidentified "Person N" / SPEAKER_X placeholders — click to show identified people only'}
                >
                  <BadgeCheck className="h-4 w-4" />
                  {namedOnly ? "Identified only" : "Everyone"}
                </Button>
              </>
            )}
            {view !== "map" && <EnrollPersonDialog />}
            <div className="flex bg-card/50 p-1 rounded-full border border-border/50 shadow-sm lg:ml-2">
              <Button size="sm" variant={view === "grid" ? "secondary" : "ghost"} className="h-8 rounded-full px-3.5 gap-1.5" onClick={() => switchView("grid")}>
                <LayoutGrid className="h-4 w-4" /> <span className="hidden sm:inline">Grid</span>
              </Button>
              <Button size="sm" variant={view === "list" ? "secondary" : "ghost"} className="h-8 rounded-full px-3.5 gap-1.5" onClick={() => switchView("list")}>
                <List className="h-4 w-4" /> <span className="hidden sm:inline">List</span>
              </Button>
              <Button size="sm" variant={view === "map" ? "secondary" : "ghost"} className="h-8 rounded-full px-3.5 gap-1.5" onClick={() => switchView("map")}>
                <Share2 className="h-4 w-4" /> <span className="hidden sm:inline">Map</span>
              </Button>
            </div>
          </div>
        </div>

        {view === "map" ? (
          <div className="flex-1 flex flex-col rounded-2xl border border-border/50 overflow-hidden bg-card/20 shadow-inner relative">
            <CoAppearanceMap />
          </div>
        ) : isLoading ? (
          view === "list" ? (
            <div className="flex flex-col gap-2">
              {[...Array(12)].map((_, i) => (
                <Card key={i} className="animate-pulse bg-muted/50 h-16 border-border/50" />
              ))}
            </div>
          ) : (
            <div className="grid gap-4 grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 2xl:grid-cols-10">
              {[...Array(24)].map((_, i) => (
                <Card key={i} className="animate-pulse bg-muted/50 h-[200px] border-border/50" />
              ))}
            </div>
          )
        ) : people?.length ? (
          <>
          {view === "list" ? (
            <div className="flex flex-col">
              {people.map((person) => {
                const isUnnamed = person.name_source !== "manual" && (person.display_name.startsWith("Person ") || person.display_name.startsWith("SPEAKER_"));
                const ringDeg = maxSpeaking > 0 ? ((person.total_speaking_seconds ?? 0) / maxSpeaking) * 360 : 0;
                
                return (
                  <Card key={person.id} className="group mb-2 border-border/50 bg-card/40 hover:bg-card hover:border-primary/40 hover:shadow-[0_0_15px_-10px_hsl(var(--primary))] transition-all duration-300 relative overflow-hidden cursor-pointer">
                    <Link href={`/people/${person.id}`} className="absolute inset-0 z-0 block">
                      <span className="sr-only">View {person.display_name}</span>
                    </Link>
                    
                    <CardContent className="p-3 flex items-center gap-4 relative z-10 pointer-events-none">
                      <div className="rounded-full p-[2px] shrink-0" style={{ background: `conic-gradient(hsl(var(--primary)) ${ringDeg}deg, hsl(var(--muted)) ${ringDeg}deg)` }}>
                         <div className="h-10 w-10 rounded-full overflow-hidden bg-muted border-2 border-background">
                            {person.thumbnail_url ? <img src={`/api/thumbnails/${person.thumbnail_url}`} className="w-full h-full object-cover" /> : <User className="h-5 w-5 text-muted-foreground/50 m-auto mt-2.5" />}
                         </div>
                      </div>
                      
                      <div className="flex-1 min-w-0">
                        {editingId === person.id ? (
                          <div className="flex items-center gap-1 max-w-[200px] pointer-events-auto" onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>
                            <Input autoFocus value={editName} onChange={(e) => setEditName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") saveEdit(e, person.id); if (e.key === "Escape") cancelEdit(e); }} placeholder="Name..." className="h-7 text-xs px-2 bg-background/50 border-primary/50 focus-visible:ring-primary/50" />
                            <Button size="icon" variant="secondary" className="h-7 w-7 shrink-0 bg-primary/20 text-primary hover:bg-primary/30" onClick={(e) => saveEdit(e, person.id)} disabled={!editName.trim() || updatePerson.isPending}><Check className="h-3 w-3" /></Button>
                            <Button size="icon" variant="secondary" className="h-7 w-7 shrink-0 bg-destructive/10 text-destructive hover:bg-destructive/20" onClick={cancelEdit}><X className="h-3 w-3" /></Button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 pointer-events-none">
                            <p className="text-sm font-semibold truncate group-hover:text-primary transition-colors">{person.display_name}</p>
                            {isUnnamed && <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" title="Unnamed" />}
                          </div>
                        )}
                      </div>
                  
                      <div className="flex items-center gap-6 shrink-0 mr-4 pointer-events-none">
                         <div className="flex flex-col items-end">
                           <span className="text-[9px] text-muted-foreground uppercase tracking-wider mb-0.5">Assets</span>
                           <span className="text-xs font-medium tabular-nums flex items-center gap-1"><Film className="h-3 w-3 text-primary/60" /> {person.asset_count}</span>
                         </div>
                         <div className="flex flex-col items-end">
                           <span className="text-[9px] text-muted-foreground uppercase tracking-wider mb-0.5">Speech</span>
                           <span className="text-xs font-medium tabular-nums flex items-center gap-1"><Mic className="h-3 w-3 text-primary/60" /> {formatSpeaking(person.total_speaking_seconds ?? 0)}</span>
                         </div>
                      </div>
                  
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 pointer-events-auto">
                         <Button size="icon" variant="ghost" className="h-8 w-8 text-primary hover:bg-primary/10" onClick={(e) => startEdit(e, person.id, person.display_name)} title="Rename"><Pencil className="h-4 w-4" /></Button>
                         <Button size="icon" variant="ghost" className="h-8 w-8 text-destructive hover:bg-destructive/10 hover:text-destructive" onClick={(e) => handleDelete(e, person.id, person.display_name)} title="Delete"><Trash2 className="h-4 w-4" /></Button>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          ) : (
            <div className="grid gap-4 grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 xl:grid-cols-8 2xl:grid-cols-10">
              {people.map((person) => {
                const isUnnamed = person.name_source !== "manual" && (person.display_name.startsWith("Person ") || person.display_name.startsWith("SPEAKER_"));
                const ringDeg = maxSpeaking > 0 ? ((person.total_speaking_seconds ?? 0) / maxSpeaking) * 360 : 0;
                
                return (
                  <Card key={person.id} className="group border-border/50 bg-card/40 hover:border-primary/40 hover:shadow-[0_0_20px_-10px_hsl(var(--primary))] transition-all duration-300 relative h-full overflow-hidden cursor-pointer p-0">
                    <Link href={`/people/${person.id}`} className="absolute inset-0 z-0 block">
                      <span className="sr-only">View {person.display_name}</span>
                    </Link>

                    <div className="relative aspect-[4/5] w-full overflow-hidden pointer-events-none">
                      {person.thumbnail_url ? (
                        <img
                          src={`/api/thumbnails/${person.thumbnail_url}`}
                          className="absolute inset-0 w-full h-full object-cover transition-transform duration-500 group-hover:scale-[1.06]"
                        />
                      ) : (
                        <div className="absolute inset-0 flex items-center justify-center bg-muted/40">
                          <User className="h-12 w-12 text-muted-foreground/40" />
                        </div>
                      )}
                      {/* legibility gradient over the lower part of the face */}
                      <div className="absolute inset-x-0 bottom-0 h-3/5 bg-gradient-to-t from-black/90 via-black/45 to-transparent" />

                      {isUnnamed && (
                        <div className="absolute top-2 right-2 w-4 h-4 rounded-full bg-black/50 backdrop-blur flex items-center justify-center" title="Unnamed person">
                          <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
                        </div>
                      )}

                      {/* name + stats over the photo */}
                      <div className="absolute inset-x-0 bottom-0 p-2.5 flex flex-col gap-1">
                        <div className="relative h-6 flex items-center pointer-events-auto">
                          {editingId === person.id ? (
                            <div className="flex items-center gap-1 w-full" onClick={(e) => { e.preventDefault(); e.stopPropagation(); }}>
                              <Input autoFocus value={editName} onChange={(e) => setEditName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") saveEdit(e, person.id); if (e.key === "Escape") cancelEdit(e); }} placeholder="Name..." className="h-6 text-xs px-2 bg-black/60 border-primary/50 focus-visible:ring-primary/50" />
                              <Button size="icon" variant="secondary" className="h-6 w-6 shrink-0 bg-primary/30 text-primary-foreground hover:bg-primary/50" onClick={(e) => saveEdit(e, person.id)} disabled={!editName.trim() || updatePerson.isPending}><Check className="h-3 w-3" /></Button>
                              <Button size="icon" variant="secondary" className="h-6 w-6 shrink-0 bg-destructive/30 text-white hover:bg-destructive/50" onClick={cancelEdit}><X className="h-3 w-3" /></Button>
                            </div>
                          ) : (
                            <p className="text-sm font-semibold text-white truncate w-full drop-shadow-sm pointer-events-none">{person.display_name}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-3 text-[11px] text-white/80 tabular-nums pointer-events-none">
                          <span className="flex items-center gap-1"><Film className="h-3 w-3 text-primary" /> {person.asset_count}</span>
                          <span className="flex items-center gap-1"><Mic className="h-3 w-3 text-primary" /> {formatSpeaking(person.total_speaking_seconds ?? 0)}</span>
                        </div>
                        {/* speaking-share bar (same measure the ring used to show) */}
                        <div className="h-0.5 rounded-full bg-white/15 overflow-hidden pointer-events-none">
                          <div className="h-full bg-primary" style={{ width: `${Math.min(100, (ringDeg / 360) * 100)}%` }} />
                        </div>
                      </div>

                      {/* hover actions */}
                      <div className="absolute top-2 left-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-auto">
                        <Button size="icon" variant="secondary" className="h-7 w-7 rounded-full bg-black/50 backdrop-blur text-white hover:bg-primary/60" onClick={(e) => startEdit(e, person.id, person.display_name)} title="Rename"><Pencil className="h-3.5 w-3.5" /></Button>
                        <Button size="icon" variant="secondary" className="h-7 w-7 rounded-full bg-black/50 backdrop-blur text-white hover:bg-destructive/70" onClick={(e) => handleDelete(e, person.id, person.display_name)} title="Delete"><Trash2 className="h-3.5 w-3.5" /></Button>
                      </div>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-4 mt-10 pb-4">
              <Button
                size="sm"
                variant="outline"
                className="rounded-full bg-card/50 hover:bg-card border-border/50 shadow-sm"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
              >
                <ChevronLeft className="h-4 w-4 mr-1" /> Previous
              </Button>
              <span className="text-sm font-medium text-muted-foreground">
                Page {page + 1} of {totalPages}
              </span>
              <Button
                size="sm"
                variant="outline"
                className="rounded-full bg-card/50 hover:bg-card border-border/50 shadow-sm"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
              >
                Next <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          )}
          </>
        ) : query ? (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground py-20">
            <div className="h-20 w-20 rounded-full bg-muted/50 flex items-center justify-center mb-6 border border-border">
              <Search className="h-8 w-8 opacity-50" />
            </div>
            <p className="text-lg font-medium text-foreground">No people match "{query}"</p>
            <p className="text-sm mt-1">Try a different name or clear the search.</p>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground py-20 max-w-md mx-auto text-center">
            <div className="h-20 w-20 rounded-full bg-muted/50 flex items-center justify-center mb-6 border border-border">
              <Users className="h-8 w-8 opacity-50" />
            </div>
            <p className="text-xl font-medium text-foreground mb-2">No people identified yet</p>
            <p className="text-sm mb-6">People appear here automatically as media is transcribed and analyzed.</p>
            <p className="text-xs p-4 rounded-xl bg-card border border-border">
              Already have processed media? It was analyzed before person identification existed —
              use <span className="text-foreground font-medium">Re-analyze Library</span> above to
              backfill voice and face profiles.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
