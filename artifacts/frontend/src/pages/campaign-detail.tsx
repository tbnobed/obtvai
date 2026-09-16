import { useState, useMemo, useEffect, useRef } from "react";
import { useLocation, useParams, Link } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetCampaign,
  getGetCampaignQueryKey,
  useUpdateCampaign,
  useDeleteCampaign,
  useCreateCampaignDeliverable,
  useUpdateCampaignDeliverable,
  useDeleteCampaignDeliverable,
  useExecuteCampaignDeliverable,
} from "@workspace/api-client-react";
import { useSemanticSearch } from "@workspace/api-client-react";
import type { SearchResult, Campaign, CampaignDeliverable as Deliverable, CampaignClip as SelectedClip } from "@workspace/api-client-react";
import { useCanEdit } from "@/lib/auth";
import { useToast } from "@/hooks/use-toast";

import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ClipThumb } from "@/components/project/clip-thumb";
import { ClipPlayerDialog, type PlayerClip } from "@/components/project/clip-player-dialog";
import { DeliverablesPanel } from "@/components/campaign/deliverables-panel";
import { formatTC } from "@/lib/timecode";
import {
  ArrowLeft, Megaphone, Pencil, Loader2, Plus, Trash2, Search, Play, CheckCircle2,
  AlertTriangle, RefreshCcw, ExternalLink, Copy, Download, FolderKanban, Info, Target, Users, KeySquare, Smile, Zap, Globe, MoreVertical
} from "lucide-react";

function fmtTime(s: number) {
  return formatTC(s, 25, false);
}

export default function CampaignDetail() {
  const { id = "" } = useParams<{ id: string }>();
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const canEdit = useCanEdit();

  const [activeTab, setActiveTab] = useState("overview");

  // --- Campaign Data & Mutators ---
  const { data: campaignResp, isLoading } = useGetCampaign(id, {
    query: {
      queryKey: getGetCampaignQueryKey(id),
      refetchInterval: (q) => {
        const c = q.state.data as { data: Campaign } | undefined;
        if (!c?.data) return false;
        const hasActive = c.data.deliverables?.some(d => ["queued", "running", "dispatch_unknown"].includes(d.status));
        return hasActive ? 3000 : false;
      }
    }
  });
  const campaign = campaignResp?.data;
  
  const updateCampaign = useUpdateCampaign();
  
  const invalidate = () => queryClient.invalidateQueries({ queryKey: getGetCampaignQueryKey(id) });

  // --- Edit Campaign Dialog ---
  const [editOpen, setEditOpen] = useState(false);
  const [editForm, setEditForm] = useState<Partial<Campaign>>({});
  const openEdit = () => {
    if (!campaign) return;
    setEditForm({
      name: campaign.name,
      brief: campaign.brief,
      objective: campaign.objective,
      audience: campaign.audience,
      key_message: campaign.key_message,
      tone: campaign.tone,
      call_to_action: campaign.call_to_action,
      channels: campaign.channels,
      languages: campaign.languages,
      due_date: campaign.due_date ? campaign.due_date.substring(0, 10) : null,
      status: campaign.status
    });
    setEditOpen(true);
  };
  const saveEdit = () => {
    if (!campaign) return;
    const payload = {
      ...editForm,
      due_date: editForm.due_date ? new Date(editForm.due_date).toISOString() : null,
    };
    updateCampaign.mutate({ campaignId: id, data: payload as any }, {
      onSuccess: () => {
        invalidate();
        setEditOpen(false);
      },
      onError: (err: any) => toast({ variant: "destructive", title: "Update failed", description: err.message })
    });
  };

  // --- Footage Search ---
  const searchMutation = useSemanticSearch();
  const [searchQuery, setSearchQuery] = useState("");
  // Populate search query initially from brief
  useEffect(() => {
    if (campaign && !searchQuery && !searchMutation.data) {
      setSearchQuery(campaign.brief);
    }
  }, [campaign, searchQuery, searchMutation.data]);

  const runSearch = () => {
    if (!searchQuery.trim()) return;
    searchMutation.mutate({ data: { query: searchQuery.trim(), search_type: "combined" } });
  };

  const [playerClip, setPlayerClip] = useState<PlayerClip | null>(null);

  const toggleClip = (r: SearchResult) => {
    if (!campaign) return;
    const exists = campaign.selected_clips.some(c => c.media_id === r.media_id && Math.abs(c.start_time - r.start_time) < 0.1);
    let nextClips;
    if (exists) {
      nextClips = campaign.selected_clips.filter(c => !(c.media_id === r.media_id && Math.abs(c.start_time - r.start_time) < 0.1));
    } else {
      nextClips = [...campaign.selected_clips, {
        media_id: r.media_id,
        start_time: r.start_time,
        end_time: r.end_time,
        filename: r.filename,
        snippet: r.snippet || undefined
      }];
    }
    updateCampaign.mutate({ campaignId: id, data: { selected_clips: nextClips } }, { onSuccess: invalidate });
  };

  const removeClip = (index: number) => {
    if (!campaign) return;
    const nextClips = [...campaign.selected_clips];
    nextClips.splice(index, 1);
    updateCampaign.mutate({ campaignId: id, data: { selected_clips: nextClips } }, { onSuccess: invalidate });
  };

  if (isLoading) {
    return (
      <div className="flex-1 p-8">
        <div className="animate-pulse h-8 w-64 bg-muted rounded mb-6" />
        <div className="animate-pulse h-64 bg-muted rounded" />
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="flex-1 p-8 text-center text-muted-foreground py-20">
        Campaign not found.
        <div className="mt-4">
          <Button variant="outline" onClick={() => navigate("/campaigns")}>
            <ArrowLeft className="h-4 w-4 mr-2" /> Back to Campaigns
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-background w-full min-w-0">
      <div className="p-4 md:p-8 pb-12 max-w-6xl mx-auto space-y-8 min-w-0">
        {/* Header */}
        <div>
          <Button variant="ghost" size="sm" className="mb-4 -ml-2 text-muted-foreground" onClick={() => navigate("/campaigns")}>
            <ArrowLeft className="h-4 w-4 mr-1" /> Campaigns
          </Button>
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <h1 className="text-3xl font-bold tracking-tight">{campaign.name}</h1>
                <Badge variant={campaign.status === "completed" ? "default" : campaign.status === "active" ? "secondary" : "outline"} className="capitalize">
                  {campaign.status}
                </Badge>
              </div>
              <div className="flex items-center gap-4 text-sm text-muted-foreground">
                <Link href={`/studio/${campaign.project_id}`} className="flex items-center gap-1.5 hover:text-primary transition-colors">
                  <FolderKanban className="h-4 w-4" /> Linked Project
                </Link>
                {campaign.due_date && <span>Due {new Date(campaign.due_date).toLocaleDateString()}</span>}
              </div>
            </div>
            {canEdit && (
              <Button variant="outline" onClick={openEdit} data-testid="button-edit-campaign">
                <Pencil className="h-4 w-4 mr-2" /> Edit Details
              </Button>
            )}
          </div>
        </div>

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="mb-6">
            <TabsTrigger value="overview">Overview & Brief</TabsTrigger>
            <TabsTrigger value="footage">Footage ({campaign.selected_clips?.length || 0})</TabsTrigger>
            <TabsTrigger value="deliverables">Deliverables ({campaign.deliverables?.length || 0})</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Creative Brief</CardTitle>
              </CardHeader>
              <CardContent className="space-y-6">
                <div>
                  <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2 mb-2"><Info className="h-4 w-4" /> The Brief</h3>
                  <p className="text-sm leading-relaxed">{campaign.brief || "No brief provided."}</p>
                </div>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-border">
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2 mb-1"><Target className="h-4 w-4" /> Objective</h3>
                    <p className="text-sm">{campaign.objective || "—"}</p>
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2 mb-1"><Users className="h-4 w-4" /> Audience</h3>
                    <p className="text-sm">{campaign.audience || "—"}</p>
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2 mb-1"><KeySquare className="h-4 w-4" /> Key Message</h3>
                    <p className="text-sm">{campaign.key_message || "—"}</p>
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2 mb-1"><Smile className="h-4 w-4" /> Tone</h3>
                    <p className="text-sm">{campaign.tone || "—"}</p>
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2 mb-1"><Zap className="h-4 w-4" /> Call to Action</h3>
                    <p className="text-sm">{campaign.call_to_action || "—"}</p>
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-muted-foreground flex items-center gap-2 mb-1"><Globe className="h-4 w-4" /> Distribution</h3>
                    <p className="text-sm">
                      {campaign.channels?.length ? campaign.channels.join(", ") : "—"} 
                      {" • "} 
                      {campaign.languages?.length ? campaign.languages.join(", ") : "—"}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="footage" className="space-y-6">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
              {/* Left: Search & Discovery */}
              <Card className="flex flex-col h-[600px]">
                <CardHeader className="pb-4 shrink-0 border-b border-border">
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Search className="h-5 w-5" /> Find Source Material
                  </CardTitle>
                  <CardDescription>Search the library for moments that match your brief.</CardDescription>
                  <div className="flex gap-2 mt-4">
                    <Input 
                      value={searchQuery} 
                      onChange={e => setSearchQuery(e.target.value)} 
                      placeholder="What are you looking for?"
                      onKeyDown={e => e.key === "Enter" && runSearch()}
                    />
                    <Button onClick={runSearch} disabled={searchMutation.isPending || !searchQuery.trim()}>
                      {searchMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : "Search"}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="flex-1 overflow-y-auto p-0">
                  {searchMutation.isPending ? (
                    <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-muted-foreground" /></div>
                  ) : searchMutation.data?.results?.length ? (
                    <div className="divide-y divide-border">
                      {searchMutation.data.results.map((r, i) => {
                        const isSelected = campaign.selected_clips.some(c => c.media_id === r.media_id && Math.abs(c.start_time - r.start_time) < 0.1);
                        return (
                          <div key={i} className={`p-4 flex gap-4 transition-colors hover:bg-muted/50 ${isSelected ? "bg-primary/5" : ""}`}>
                            <button
                              type="button"
                              data-testid="button-preview-clip"
                              className="shrink-0 relative group"
                              onClick={() => setPlayerClip({ media_id: r.media_id, start_time: r.start_time, end_time: r.end_time, label: r.snippet || undefined, filename: r.filename })}
                            >
                              <ClipThumb url={r.thumbnail_url} mediaId={r.media_id} time={r.start_time} className="h-16 w-28 rounded-md" />
                              <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity rounded-md">
                                <Play className="h-6 w-6 text-white" />
                              </div>
                            </button>
                            <div className="flex-1 min-w-0">
                              <h4 className="font-medium text-sm truncate" title={r.filename}>{r.filename}</h4>
                              <p className="text-xs text-muted-foreground mt-1">
                                {fmtTime(r.start_time)} – {fmtTime(r.end_time)} · {(r.score * 100).toFixed(0)}% match
                              </p>
                              {r.snippet && <p className="text-sm mt-2 italic text-muted-foreground line-clamp-2">"{r.snippet}"</p>}
                            </div>
                            {canEdit && (
                              <div className="shrink-0 flex items-center">
                                <Button size="sm" variant={isSelected ? "secondary" : "outline"} onClick={() => toggleClip(r)} disabled={updateCampaign.isPending} data-testid={`button-add-clip-${r.media_id}`}>
                                  {isSelected ? <CheckCircle2 className="h-4 w-4 mr-2 text-primary" /> : <Plus className="h-4 w-4 mr-2" />}
                                  {isSelected ? "Added" : "Add"}
                                </Button>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : searchMutation.isSuccess ? (
                    <div className="text-center py-12 text-muted-foreground">No matches found.</div>
                  ) : (
                    <div className="text-center py-12 text-muted-foreground">Search to find relevant moments.</div>
                  )}
                </CardContent>
              </Card>

              {/* Right: Selected Clips */}
              <Card className="flex flex-col h-[600px] border-primary/20">
                <CardHeader className="pb-4 shrink-0 border-b border-border bg-primary/5">
                  <CardTitle className="text-lg">Selected Clips</CardTitle>
                  <CardDescription>Moments saved for this campaign's deliverables.</CardDescription>
                </CardHeader>
                <CardContent className="flex-1 overflow-y-auto p-0">
                  {campaign.selected_clips?.length > 0 ? (
                    <div className="divide-y divide-border">
                      {campaign.selected_clips.map((c, i) => (
                        <div key={i} className="p-4 flex gap-4 hover:bg-muted/50 transition-colors">
                           <button
                              type="button"
                              data-testid="button-preview-clip"
                              className="shrink-0 relative group"
                              onClick={() => setPlayerClip({ media_id: c.media_id, start_time: c.start_time, end_time: c.end_time, label: c.snippet, filename: c.filename || "Clip" })}
                            >
                              <ClipThumb mediaId={c.media_id} time={c.start_time} className="h-16 w-28 rounded-md" />
                              <div className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity rounded-md">
                                <Play className="h-6 w-6 text-white" />
                              </div>
                            </button>
                            <div className="flex-1 min-w-0 flex flex-col justify-center">
                              <h4 className="font-medium text-sm truncate">{c.filename || "Unknown media"}</h4>
                              <p className="text-xs text-muted-foreground mt-1">
                                {fmtTime(c.start_time)} – {fmtTime(c.end_time)}
                              </p>
                              {c.snippet && <p className="text-sm mt-1 truncate text-muted-foreground">"{c.snippet}"</p>}
                            </div>
                            {canEdit && (
                              <div className="shrink-0 flex items-center">
                                <Button size="icon" variant="ghost" className="text-muted-foreground hover:text-destructive" onClick={() => removeClip(i)}>
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-20 text-muted-foreground flex flex-col items-center">
                      <Target className="h-8 w-8 mb-3 opacity-20" />
                      <p>No clips selected yet.</p>
                      <p className="text-sm mt-1">Add clips from search to inform generations.</p>
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          <TabsContent value="deliverables" className="space-y-6">
            <DeliverablesPanel campaign={campaign} invalidate={invalidate} canEdit={canEdit} />
          </TabsContent>
        </Tabs>

      </div>

      {/* Edit Campaign Dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Edit Campaign</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4 py-4">
            <div className="space-y-2 col-span-2">
              <Label htmlFor="edit-name">Name</Label>
              <Input id="edit-name" value={editForm.name || ""} onChange={e => setEditForm({ ...editForm, name: e.target.value })} />
            </div>
            <div className="space-y-2 col-span-2 md:col-span-1">
              <Label>Status</Label>
              <Select value={editForm.status} onValueChange={(v: any) => setEditForm({ ...editForm, status: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="draft">Draft</SelectItem>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="archived">Archived</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2 col-span-2 md:col-span-1">
              <Label htmlFor="edit-due_date">Due Date</Label>
              <Input id="edit-due_date" type="date" value={editForm.due_date || ""} onChange={e => setEditForm({ ...editForm, due_date: e.target.value })} />
            </div>
            <div className="space-y-2 col-span-2">
              <Label htmlFor="edit-brief">Brief</Label>
              <Textarea id="edit-brief" value={editForm.brief || ""} onChange={e => setEditForm({ ...editForm, brief: e.target.value })} rows={3} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-objective">Objective</Label>
              <Input id="edit-objective" value={editForm.objective || ""} onChange={e => setEditForm({ ...editForm, objective: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-audience">Audience</Label>
              <Input id="edit-audience" value={editForm.audience || ""} onChange={e => setEditForm({ ...editForm, audience: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-key_message">Key Message</Label>
              <Input id="edit-key_message" value={editForm.key_message || ""} onChange={e => setEditForm({ ...editForm, key_message: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-tone">Tone</Label>
              <Input id="edit-tone" value={editForm.tone || ""} onChange={e => setEditForm({ ...editForm, tone: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-call_to_action">Call to Action</Label>
              <Input id="edit-call_to_action" value={editForm.call_to_action || ""} onChange={e => setEditForm({ ...editForm, call_to_action: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-channels">Channels</Label>
              <Input id="edit-channels" value={(editForm.channels || []).join(", ")} onChange={e => setEditForm({ ...editForm, channels: e.target.value.split(",").map(s => s.trim()) })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-languages">Languages</Label>
              <Input id="edit-languages" value={(editForm.languages || []).join(", ")} onChange={e => setEditForm({ ...editForm, languages: e.target.value.split(",").map(s => s.trim()) })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>Cancel</Button>
            <Button onClick={saveEdit} disabled={!editForm.name?.trim() || updateCampaign.isPending}>
              {updateCampaign.isPending ? "Saving..." : "Save Changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ClipPlayerDialog clip={playerClip} onClose={() => setPlayerClip(null)} />
    </div>
  );
}

