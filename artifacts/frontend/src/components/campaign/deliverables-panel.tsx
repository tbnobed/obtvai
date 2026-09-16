import { useState, useEffect } from "react";
import { Link } from "wouter";
import {
  useCreateCampaignDeliverable,
  useUpdateCampaignDeliverable,
  useDeleteCampaignDeliverable,
  useExecuteCampaignDeliverable,
} from "@workspace/api-client-react";
import type { Campaign, CampaignDeliverable as Deliverable } from "@workspace/api-client-react";
import { useToast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Info, Plus, Trash2, MoreVertical, Loader2, CheckCircle2, AlertTriangle, ExternalLink, RefreshCcw, Play, Copy, Download, Pencil } from "lucide-react";

export function DeliverableFormDialog({ 
  open, 
  onOpenChange, 
  initialData, 
  onSubmit, 
  isPending, 
  isEdit = false,
  isExecuted = false
}: { 
  open: boolean; 
  onOpenChange: (open: boolean) => void; 
  initialData: any; 
  onSubmit: (data: any) => void; 
  isPending: boolean;
  isEdit?: boolean;
  isExecuted?: boolean;
}) {
  const [form, setForm] = useState(initialData);

  // Sync form when modal opens with new initialData
  useEffect(() => {
    if (open) {
      setForm(initialData);
    }
  }, [open, initialData]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Deliverable" : "New Deliverable"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor={`deliv-kind-${isEdit ? 'edit' : 'new'}`}>Kind</Label>
              <Select 
                value={form.kind} 
                onValueChange={v => setForm({ ...form, kind: v })}
                disabled={isEdit && isExecuted}
              >
                <SelectTrigger id={`deliv-kind-${isEdit ? 'edit' : 'new'}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="promo">Promo Video</SelectItem>
                  <SelectItem value="reel">Vertical Reel</SelectItem>
                  <SelectItem value="thumbnail">Thumbnail Image</SelectItem>
                  <SelectItem value="social_copy">Social Copy (Text)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor={`deliv-label-${isEdit ? 'edit' : 'new'}`}>Label</Label>
              <Input id={`deliv-label-${isEdit ? 'edit' : 'new'}`} value={form.label} onChange={e => setForm({ ...form, label: e.target.value })} placeholder="30s Teaser" />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`deliv-channel-${isEdit ? 'edit' : 'new'}`}>Channel</Label>
              <Input id={`deliv-channel-${isEdit ? 'edit' : 'new'}`} value={form.channel} onChange={e => setForm({ ...form, channel: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`deliv-language-${isEdit ? 'edit' : 'new'}`}>Language</Label>
              <Input id={`deliv-language-${isEdit ? 'edit' : 'new'}`} value={form.language} onChange={e => setForm({ ...form, language: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`deliv-duration-${isEdit ? 'edit' : 'new'}`}>Duration (sec)</Label>
              <Input id={`deliv-duration-${isEdit ? 'edit' : 'new'}`} type="number" value={form.target_duration_seconds || ""} onChange={e => setForm({ ...form, target_duration_seconds: e.target.value })} disabled={form.kind === "thumbnail" || form.kind === "social_copy"} />
            </div>
            <div className="space-y-2">
              <Label htmlFor={`deliv-aspect-${isEdit ? 'edit' : 'new'}`}>Aspect Ratio</Label>
              <Input id={`deliv-aspect-${isEdit ? 'edit' : 'new'}`} value={form.aspect_ratio} onChange={e => setForm({ ...form, aspect_ratio: e.target.value })} disabled={form.kind === "social_copy"} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor={`deliv-notes-${isEdit ? 'edit' : 'new'}`}>Notes</Label>
            <Textarea id={`deliv-notes-${isEdit ? 'edit' : 'new'}`} value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} placeholder="Specific instructions for generation..." rows={2} />
          </div>
          <p className="text-xs text-muted-foreground flex items-start gap-1.5 bg-muted p-2 rounded">
            <Info className="h-4 w-4 shrink-0" /> 
            Does not automatically translate or dub videos. This indicates intended output settings.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => onSubmit(form)} disabled={!form.label.trim() || isPending}>
            {isPending ? "Saving..." : (isEdit ? "Save Changes" : "Add Deliverable")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function DeliverablesPanel({ campaign, invalidate, canEdit }: { campaign: Campaign, invalidate: () => void, canEdit: boolean }) {
  const [createOpen, setCreateOpen] = useState(false);
  const createMutation = useCreateCampaignDeliverable();
  const defaultForm = {
    kind: "promo" as any,
    label: "",
    channel: campaign.channels?.[0] || "",
    language: campaign.languages?.[0] || "en",
    target_duration_seconds: "30",
    aspect_ratio: "16:9",
    notes: ""
  };

  const submitCreate = (formData: any) => {
    createMutation.mutate({
      campaignId: campaign.id,
      data: {
        kind: formData.kind,
        label: formData.label.trim(),
        channel: formData.channel.trim() || "web",
        language: formData.language.trim() || "en",
        target_duration_seconds: formData.target_duration_seconds ? parseInt(formData.target_duration_seconds, 10) : null,
        aspect_ratio: formData.aspect_ratio.trim() || "16:9",
        notes: formData.notes.trim() || undefined
      }
    }, {
      onSuccess: () => {
        invalidate();
        setCreateOpen(false);
      }
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-semibold">Deliverables</h2>
        {canEdit && (
          <Button onClick={() => setCreateOpen(true)} size="sm">
            <Plus className="h-4 w-4 mr-2" /> Add Deliverable
          </Button>
        )}
      </div>

      <DeliverableFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        initialData={defaultForm}
        onSubmit={submitCreate}
        isPending={createMutation.isPending}
      />

      {campaign.deliverables?.length ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {campaign.deliverables.map(d => (
            <DeliverableCard key={d.id} deliverable={d} campaign={campaign} invalidate={invalidate} canEdit={canEdit} />
          ))}
        </div>
      ) : (
        <div className="text-center py-16 border border-dashed border-border rounded-lg text-muted-foreground">
          <p>No deliverables planned.</p>
          {canEdit && (
            <Button variant="outline" className="mt-4" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4 mr-2" /> Plan your first output
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

function DeliverableCard({ deliverable, campaign, invalidate, canEdit }: { deliverable: Deliverable, campaign: Campaign, invalidate: () => void, canEdit: boolean }) {
  const { toast } = useToast();
  const executeMutation = useExecuteCampaignDeliverable();
  const deleteMutation = useDeleteCampaignDeliverable();
  const updateMutation = useUpdateCampaignDeliverable();
  
  const isActive = ["queued", "running"].includes(deliverable.status);
  const isReady = deliverable.status === "ready";
  const isDraftReady = deliverable.status === "draft_ready";
  const isFailed = deliverable.status === "failed";
  const isDispatchUnknown = deliverable.status === "dispatch_unknown";
  
  // Has it ever been executed? Once executed, kind cannot change.
  const isExecuted = isActive || isReady || isDraftReady || isFailed || isDispatchUnknown || deliverable.job_reference != null;

  const [editOpen, setEditOpen] = useState(false);

  const handleUpdate = (formData: any) => {
    updateMutation.mutate({
      campaignId: campaign.id,
      deliverableId: deliverable.id,
      data: {
        label: formData.label.trim(),
        channel: formData.channel.trim(),
        language: formData.language.trim(),
        target_duration_seconds: formData.target_duration_seconds ? parseInt(formData.target_duration_seconds, 10) : null,
        aspect_ratio: formData.aspect_ratio.trim(),
        notes: formData.notes?.trim() || null
      }
    }, {
      onSuccess: () => {
        invalidate();
        setEditOpen(false);
        toast({ title: "Deliverable updated" });
      },
      onError: (err: any) => toast({ variant: "destructive", title: "Update failed", description: err.message })
    });
  };

  const handleExecute = (retry = false) => {
    executeMutation.mutate({ campaignId: campaign.id, deliverableId: deliverable.id, data: retry ? { retry: true } : undefined }, {
      onSuccess: () => {
        invalidate();
        toast({ title: "Generation started", description: `${deliverable.label} is processing.` });
      },
      onError: (err: any) => toast({ variant: "destructive", title: "Execution failed", description: err.message })
    });
  };

  const handleDelete = () => {
    deleteMutation.mutate({ campaignId: campaign.id, deliverableId: deliverable.id }, {
      onSuccess: invalidate,
      onError: (err: any) => toast({ variant: "destructive", title: "Delete failed", description: err.message })
    });
  };

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text);
    toast({ title: "Copied to clipboard" });
  };

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3 border-b border-border">
        <div className="flex justify-between items-start">
          <div>
            <Badge variant="outline" className="uppercase text-[10px] tracking-wider mb-2 bg-muted">{deliverable.kind.replace("_", " ")}</Badge>
            <CardTitle className="text-base">{deliverable.label}</CardTitle>
          </div>
          {canEdit && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="icon" variant="ghost" className="h-8 w-8 text-muted-foreground" data-testid="button-deliverable-menu"><MoreVertical className="h-4 w-4" /></Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem 
                  onClick={() => setEditOpen(true)} 
                  disabled={isActive}
                  data-testid="button-edit-deliverable"
                >
                  <Pencil className="h-4 w-4 mr-2" /> Edit
                </DropdownMenuItem>
                <DropdownMenuItem className="text-red-400 focus:text-red-400" onClick={handleDelete} data-testid="button-delete-deliverable">
                  <Trash2 className="h-4 w-4 mr-2" /> Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 py-4 text-sm space-y-3">
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-muted-foreground">
          <div><span className="font-medium">Channel:</span> {deliverable.channel}</div>
          <div><span className="font-medium">Lang:</span> {deliverable.language}</div>
          {deliverable.target_duration_seconds != null && <div><span className="font-medium">Dur:</span> {deliverable.target_duration_seconds}s</div>}
          {deliverable.kind !== "social_copy" && <div><span className="font-medium">Aspect:</span> {deliverable.aspect_ratio}</div>}
        </div>
        {deliverable.notes && (
          <div className="bg-muted/50 p-2 rounded border border-border/50 text-xs italic">
            "{deliverable.notes}"
          </div>
        )}
        
        {/* Output Section */}
        {isReady && deliverable.kind === "social_copy" && deliverable.output_text && (
          <div className="mt-4 p-3 bg-card border border-border rounded-md shadow-sm relative group">
            <div className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <Button size="icon" variant="secondary" className="h-7 w-7" onClick={() => copyText(deliverable.output_text!)}>
                <Copy className="h-3.5 w-3.5" />
              </Button>
            </div>
            <p className="whitespace-pre-wrap text-sm">{deliverable.output_text}</p>
          </div>
        )}
        
        {isReady && deliverable.kind === "thumbnail" && deliverable.output_url && (
          <div className="mt-4 rounded-md overflow-hidden border border-border relative group aspect-video bg-muted flex items-center justify-center">
            <img src={deliverable.output_url} alt="Thumbnail" className="w-full h-full object-cover" />
            <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
              <Button variant="secondary" onClick={() => window.open(deliverable.output_url!, "_blank")}>
                <Download className="h-4 w-4 mr-2" /> Download
              </Button>
            </div>
          </div>
        )}

      </CardContent>
      <CardFooter className="pt-3 border-t border-border bg-muted/20 flex flex-col items-stretch justify-between gap-3">
        <div className="flex items-center justify-between w-full">
          <div className="flex items-center gap-2 text-sm">
            {isActive ? (
              <span className="flex items-center text-primary font-medium">
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> {deliverable.status}
              </span>
            ) : isReady ? (
              <span className="flex items-center text-emerald-500 font-medium">
                <CheckCircle2 className="h-4 w-4 mr-1.5" /> Ready
              </span>
            ) : isDraftReady ? (
              <span className="flex items-center text-blue-500 font-medium" title="Editable draft cut created">
                <CheckCircle2 className="h-4 w-4 mr-1.5" /> Draft Ready
              </span>
            ) : isDispatchUnknown ? (
              <span className="flex items-center text-amber-500 font-medium" title="Job dispatch state unknown; server will reconcile">
                <AlertTriangle className="h-4 w-4 mr-1.5" /> Dispatch Unknown
              </span>
            ) : isFailed ? (
              <span className="flex items-center text-red-500 font-medium" title={deliverable.error || "Execution failed"}>
                <AlertTriangle className="h-4 w-4 mr-1.5" /> Failed
              </span>
            ) : (
              <span className="text-muted-foreground capitalize">{deliverable.status}</span>
            )}
          </div>
          
          <div className="flex items-center gap-2">
            {isDraftReady && (
              <Link href={`/studio/${campaign.project_id}`}>
                <Button size="sm" variant="outline" className="bg-background">
                  <ExternalLink className="h-3.5 w-3.5 mr-1.5" /> Open in Studio
                </Button>
              </Link>
            )}
            
            {isDispatchUnknown && (
              <Link href={`/studio/${campaign.project_id}`}>
                <Button size="sm" variant="outline" className="bg-background text-amber-500 hover:text-amber-600 hover:bg-amber-500/10" data-testid="button-inspect-job">
                  <ExternalLink className="h-3.5 w-3.5 mr-1.5" /> Inspect Job in Studio
                </Button>
              </Link>
            )}
            
            {canEdit && !isActive && !isReady && !isDraftReady && !isDispatchUnknown && (
              <Button size="sm" onClick={() => handleExecute(isFailed)} variant={isFailed ? "outline" : "default"} data-testid="button-generate">
                {isFailed ? <RefreshCcw className="h-3.5 w-3.5 mr-1.5" /> : <Play className="h-3.5 w-3.5 mr-1.5" />}
                {isFailed ? "Retry" : "Generate"}
              </Button>
            )}
          </div>
        </div>
        
        {/* Render error directly so it's not hidden behind a tooltip for active/queued issues */}
        {deliverable.error && (
          <div className="bg-red-500/10 text-red-500 p-2 rounded border border-red-500/20 text-xs w-full">
            <AlertTriangle className="h-3.5 w-3.5 inline mr-1" />
            {deliverable.error}
          </div>
        )}
      </CardFooter>

      {canEdit && (
        <DeliverableFormDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          initialData={{
            kind: deliverable.kind,
            label: deliverable.label,
            channel: deliverable.channel,
            language: deliverable.language,
            target_duration_seconds: deliverable.target_duration_seconds?.toString() || "",
            aspect_ratio: deliverable.aspect_ratio,
            notes: deliverable.notes || ""
          }}
          onSubmit={handleUpdate}
          isPending={updateMutation.isPending}
          isEdit={true}
          isExecuted={isExecuted}
        />
      )}
    </Card>
  );
}
