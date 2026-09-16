import { useState } from "react";
import { useLocation } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import { useListCampaigns, getListCampaignsQueryKey, useCreateCampaign, useUpdateCampaign, useDeleteCampaign, useCreateCampaignDeliverable } from "@workspace/api-client-react";
import { useListProjects, getListProjectsQueryKey } from "@workspace/api-client-react";
import type { Campaign } from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Megaphone, Plus, MoreVertical, Pencil, Trash2, Loader2, Archive, ArchiveRestore, CheckSquare } from "lucide-react";
import { useToast } from "@/hooks/use-toast";

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function Campaigns() {
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  
  const { data: campaignsResp, isLoading } = useListCampaigns();
  const campaigns = campaignsResp?.data;
  const { data: projects } = useListProjects();
  
  const createMutation = useCreateCampaign();
  const updateMutation = useUpdateCampaign();
  const deleteMutation = useDeleteCampaign();
  const createDeliverable = useCreateCampaignDeliverable();

  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Campaign | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  // New Campaign Form State
  const [formData, setFormData] = useState({
    name: "",
    projectMode: "new" as "new" | "existing",
    projectId: "",
    projectName: "",
    brief: "",
    objective: "",
    audience: "",
    key_message: "",
    tone: "",
    call_to_action: "",
    channels: "",
    languages: "en",
    due_date: "",
    createStandardPackage: true
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: getListCampaignsQueryKey() });

  const submitCreate = async () => {
    if (!formData.name.trim() || !formData.brief.trim()) return;
    if (formData.projectMode === "existing" && !formData.projectId) {
      toast({ variant: "destructive", title: "Select a project", description: "Choose the existing project to link to this campaign." });
      return;
    }
    
    const payload: any = {
      name: formData.name.trim(),
      brief: formData.brief.trim(),
      objective: formData.objective.trim(),
      audience: formData.audience.trim(),
      key_message: formData.key_message.trim(),
      tone: formData.tone.trim(),
      call_to_action: formData.call_to_action.trim(),
      channels: formData.channels.split(",").map(c => c.trim()).filter(Boolean),
      languages: formData.languages.split(",").map(l => l.trim()).filter(Boolean),
      due_date: formData.due_date ? new Date(formData.due_date).toISOString() : null,
      selected_clips: [],
      status: "draft"
    };

    if (formData.projectMode === "existing" && formData.projectId) {
      payload.project_id = formData.projectId;
    } else {
      payload.project_action = { name: formData.projectName.trim() || `${formData.name.trim()} Project` };
    }

    createMutation.mutate({ data: payload }, {
      onSuccess: async (resp) => {
        const c = resp.data;
        if (formData.createStandardPackage) {
          // Create standard package
          try {
            const channels = payload.channels || [];
            const mainChannel = channels.length > 0 ? channels[0] : "all";
            const reelChannel = channels.includes("instagram") ? "instagram" : channels.includes("tiktok") ? "tiktok" : mainChannel;
            const thumbChannel = channels.includes("youtube") ? "youtube" : mainChannel;
            const copyChannel = channels.includes("twitter") ? "twitter" : channels.includes("linkedin") ? "linkedin" : mainChannel;

            await Promise.all([
              createDeliverable.mutateAsync({ campaignId: c.id, data: { kind: "promo", label: "30s Promo", channel: mainChannel, language: payload.languages[0] || "en", target_duration_seconds: 30, aspect_ratio: "16:9" } }),
              createDeliverable.mutateAsync({ campaignId: c.id, data: { kind: "reel", label: "Vertical Reel", channel: reelChannel, language: payload.languages[0] || "en", target_duration_seconds: 15, aspect_ratio: "9:16" } }),
              createDeliverable.mutateAsync({ campaignId: c.id, data: { kind: "thumbnail", label: "Hero Thumbnail", channel: thumbChannel, language: payload.languages[0] || "en", target_duration_seconds: null, aspect_ratio: "16:9" } }),
              createDeliverable.mutateAsync({ campaignId: c.id, data: { kind: "social_copy", label: "Social Copy", channel: copyChannel, language: payload.languages[0] || "en", target_duration_seconds: null, aspect_ratio: "text" } }),
            ]);
          } catch (err) {
            toast({
              variant: "destructive",
              title: "Campaign created; package incomplete",
              description: "Some deliverables could not be added. Check the deliverables list and add any missing items.",
            });
          }
        }
        
        invalidate();
        setCreateOpen(false);
        navigate(`/campaigns/${c.id}`);
      },
      onError: (err: any) => {
        toast({
          variant: "destructive",
          title: "Failed to create campaign",
          description: err.message
        });
      }
    });
  };

  const submitDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate({ campaignId: deleteTarget.id }, {
      onSuccess: () => {
        invalidate();
        setDeleteTarget(null);
        toast({ title: "Campaign deleted" });
      },
      onError: (err: any) => {
        toast({ variant: "destructive", title: "Could not delete campaign", description: err.message });
      }
    });
  };

  const toggleArchive = (c: Campaign) => {
    updateMutation.mutate(
      { campaignId: c.id, data: { status: c.status === "archived" ? "draft" : "archived" } },
      { onSuccess: invalidate }
    );
  };

  const active = campaigns?.filter(c => c.status !== "archived") ?? [];
  const archived = campaigns?.filter(c => c.status === "archived") ?? [];
  const visible = showArchived ? archived : active;

  return (
    <div className="flex-1 p-4 md:p-8 overflow-y-auto w-full min-w-0">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Campaigns</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Plan deliverables, write briefs, and execute marketing assets.
          </p>
        </div>
        <div className="flex gap-2">
          {archived.length > 0 && (
            <Button variant="outline" onClick={() => setShowArchived(!showArchived)}>
              {showArchived ? "Show active" : `Archived (${archived.length})`}
            </Button>
          )}
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4 mr-2" /> New Campaign
          </Button>
        </div>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Megaphone className="h-5 w-5" /> New Campaign
            </DialogTitle>
            <DialogDescription>Define your marketing brief and project links.</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-4 py-4">
            <div className="space-y-2 col-span-2">
              <Label htmlFor="create-name">Campaign Name *</Label>
              <Input
                id="create-name"
                value={formData.name}
                onChange={e => setFormData({ ...formData, name: e.target.value })}
                placeholder="Summer Sale 2025"
              />
            </div>
            
            <div className="space-y-2 col-span-2 md:col-span-1">
              <Label>Link to Project</Label>
              <Select value={formData.projectMode} onValueChange={(v: any) => setFormData({ ...formData, projectMode: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="new">Create new project</SelectItem>
                  <SelectItem value="existing">Use existing project</SelectItem>
                </SelectContent>
              </Select>
            </div>
            
            {formData.projectMode === "existing" ? (
              <div className="space-y-2 col-span-2 md:col-span-1">
                <Label>Select Project</Label>
                <Select value={formData.projectId} onValueChange={v => setFormData({ ...formData, projectId: v })}>
                  <SelectTrigger><SelectValue placeholder="Select a project..." /></SelectTrigger>
                  <SelectContent>
                    {projects?.map(p => (
                      <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <div className="space-y-2 col-span-2 md:col-span-1">
                <Label htmlFor="create-project-name">New Project Name (optional)</Label>
                <Input
                  id="create-project-name"
                  value={formData.projectName}
                  onChange={e => setFormData({ ...formData, projectName: e.target.value })}
                  placeholder="Leave blank to use campaign name"
                />
              </div>
            )}
            
            <div className="space-y-2 col-span-2">
              <Label htmlFor="create-brief">Brief *</Label>
              <Textarea
                id="create-brief"
                value={formData.brief}
                onChange={e => setFormData({ ...formData, brief: e.target.value })}
                placeholder="High-level description of what we are doing and why..."
                rows={3}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-objective">Objective</Label>
              <Input
                id="create-objective"
                value={formData.objective}
                onChange={e => setFormData({ ...formData, objective: e.target.value })}
                placeholder="Drive signups..."
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-audience">Audience</Label>
              <Input
                id="create-audience"
                value={formData.audience}
                onChange={e => setFormData({ ...formData, audience: e.target.value })}
                placeholder="Young professionals..."
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-key_message">Key Message</Label>
              <Input
                id="create-key_message"
                value={formData.key_message}
                onChange={e => setFormData({ ...formData, key_message: e.target.value })}
                placeholder="Save time with AI..."
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-tone">Tone</Label>
              <Input
                id="create-tone"
                value={formData.tone}
                onChange={e => setFormData({ ...formData, tone: e.target.value })}
                placeholder="Energetic, professional..."
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-call_to_action">Call to Action</Label>
              <Input
                id="create-call_to_action"
                value={formData.call_to_action}
                onChange={e => setFormData({ ...formData, call_to_action: e.target.value })}
                placeholder="Sign up today at..."
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-channels">Channels (comma separated)</Label>
              <Input
                id="create-channels"
                value={formData.channels}
                onChange={e => setFormData({ ...formData, channels: e.target.value })}
                placeholder="instagram, youtube, twitter..."
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-languages">Languages (comma separated)</Label>
              <Input
                id="create-languages"
                value={formData.languages}
                onChange={e => setFormData({ ...formData, languages: e.target.value })}
                placeholder="en, es..."
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="create-due_date">Due Date</Label>
              <Input
                id="create-due_date"
                type="date"
                value={formData.due_date}
                onChange={e => setFormData({ ...formData, due_date: e.target.value })}
              />
            </div>
            
            <div className="col-span-2 flex items-center gap-2 mt-2">
              <input 
                type="checkbox" 
                id="create-pkg" 
                checked={formData.createStandardPackage}
                onChange={e => setFormData({...formData, createStandardPackage: e.target.checked})}
                className="h-4 w-4 rounded border-gray-300"
              />
              <Label htmlFor="create-pkg" className="font-normal cursor-pointer">
                Start with a standard deliverable package (Promo, Reel, Thumbnail, Social Copy)
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button onClick={submitCreate} disabled={!formData.name.trim() || !formData.brief.trim() || createMutation.isPending || (formData.projectMode === "existing" && !formData.projectId)}>
              {createMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Create Campaign
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete "{deleteTarget?.name}"?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            This will remove the campaign and its deliverables. The linked Studio project, source media, and generated files are kept.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="destructive" onClick={submitDelete} disabled={deleteMutation.isPending}>
              {deleteMutation.isPending ? "Deleting..." : "Delete Campaign"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {isLoading ? (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {[...Array(3)].map((_, i) => <Card key={i} className="animate-pulse h-40 bg-muted" />)}
        </div>
      ) : visible.length ? (
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {visible.map(c => (
            <Card
              key={c.id}
              className={`cursor-pointer hover:border-primary/50 transition-colors ${c.status === "archived" ? "opacity-70" : ""}`}
              onClick={() => navigate(`/campaigns/${c.id}`)}
            >
              <CardHeader className="flex flex-row items-start justify-between space-y-0">
                <div className="min-w-0 pr-4">
                  <div className="flex items-center gap-2 mb-1">
                    <CardTitle className="truncate text-lg">{c.name}</CardTitle>
                    <Badge variant={c.status === "completed" ? "default" : c.status === "active" ? "secondary" : "outline"} className="capitalize">
                      {c.status}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground line-clamp-2" title={c.brief}>{c.brief}</p>
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size="icon" variant="ghost" className="h-8 w-8 shrink-0 text-muted-foreground" onClick={e => e.stopPropagation()}>
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" onClick={e => e.stopPropagation()}>
                    <DropdownMenuItem onClick={() => navigate(`/campaigns/${c.id}`)} data-testid="button-edit-campaign">
                      <Pencil className="h-4 w-4 mr-2" /> Edit
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => toggleArchive(c)}>
                      {c.status === "archived"
                        ? <><ArchiveRestore className="h-4 w-4 mr-2" /> Unarchive</>
                        : <><Archive className="h-4 w-4 mr-2" /> Archive</>}
                    </DropdownMenuItem>
                    <DropdownMenuItem className="text-red-400 focus:text-red-400" onClick={() => setDeleteTarget(c)} data-testid="button-delete-campaign">
                      <Trash2 className="h-4 w-4 mr-2" /> Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm text-muted-foreground">
                  <span className="flex items-center gap-1.5" title="Deliverables">
                    <CheckSquare className="h-3.5 w-3.5" /> {c.deliverables?.length || 0} tasks
                  </span>
                  {c.due_date && (
                    <span className="flex items-center gap-1.5" title="Due Date">
                      Due {new Date(c.due_date).toLocaleDateString()}
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground mt-4">
                  Last updated {relativeTime(c.updated_at ?? c.created_at)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="text-center text-muted-foreground py-20 border border-dashed border-border rounded-lg">
          <Megaphone className="h-8 w-8 mx-auto mb-3 opacity-50" />
          <p>{showArchived ? "No archived campaigns." : "No campaigns yet."}</p>
          {!showArchived && (
            <Button className="mt-4" variant="outline" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4 mr-2" /> Start your first campaign
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
