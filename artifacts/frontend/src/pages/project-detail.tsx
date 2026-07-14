import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetProject,
  getGetProjectQueryKey,
  getListProjectsQueryKey,
  useUpdateProject,
  useListClipLists,
  useListStories,
  useListReels,
  useListRenders,
} from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ArrowLeft, Search, FileText, Scissors, BookOpen, Wand2, Clapperboard,
  Play, Download, Loader2, Save,
} from "lucide-react";

function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "success" ? "default" :
    status === "error" ? "destructive" : "secondary";
  return <Badge variant={variant} className="capitalize">{status}</Badge>;
}

export default function ProjectDetail() {
  const { id = "" } = useParams<{ id: string }>();
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();

  const { data: project, isLoading } = useGetProject(id);
  const updateMutation = useUpdateProject();

  const { data: clipLists } = useListClipLists({ project_id: id });
  const { data: stories } = useListStories({ project_id: id });
  const { data: reels } = useListReels({ project_id: id });
  const { data: renders } = useListRenders({ project_id: id });

  const [script, setScript] = useState("");
  const [scriptDirty, setScriptDirty] = useState(false);

  useEffect(() => {
    if (project && !scriptDirty) setScript(project.script ?? "");
  }, [project, scriptDirty]);

  const saveScript = () => {
    updateMutation.mutate(
      { id, data: { script } },
      {
        onSuccess: () => {
          setScriptDirty(false);
          queryClient.invalidateQueries({ queryKey: getGetProjectQueryKey(id) });
          queryClient.invalidateQueries({ queryKey: getListProjectsQueryKey() });
        },
      },
    );
  };

  if (isLoading) {
    return (
      <div className="flex-1 p-8">
        <div className="animate-pulse h-8 w-64 bg-muted rounded mb-6" />
        <div className="animate-pulse h-64 bg-muted rounded" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex-1 p-8 text-center text-muted-foreground py-20">
        Project not found.
        <div className="mt-4">
          <Button variant="outline" onClick={() => navigate("/projects")}>
            <ArrowLeft className="h-4 w-4 mr-2" /> Back to Projects
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex items-start justify-between mb-6">
        <div className="min-w-0">
          <Button variant="ghost" size="sm" className="mb-2 -ml-2 text-muted-foreground" onClick={() => navigate("/projects")}>
            <ArrowLeft className="h-4 w-4 mr-1" /> Projects
          </Button>
          <h1 className="text-3xl font-bold tracking-tight truncate">{project.name}</h1>
          {project.description && (
            <p className="text-sm text-muted-foreground mt-1">{project.description}</p>
          )}
        </div>
      </div>

      <Tabs defaultValue="find">
        <TabsList className="mb-6">
          <TabsTrigger value="find"><Search className="h-4 w-4 mr-2" /> Find</TabsTrigger>
          <TabsTrigger value="assemble"><Scissors className="h-4 w-4 mr-2" /> Assemble</TabsTrigger>
          <TabsTrigger value="cut"><Wand2 className="h-4 w-4 mr-2" /> Cut</TabsTrigger>
          <TabsTrigger value="deliver"><Clapperboard className="h-4 w-4 mr-2" /> Deliver</TabsTrigger>
        </TabsList>

        <TabsContent value="find" className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="flex items-center gap-2 text-base">
                <FileText className="h-4 w-4" /> Working Script
              </CardTitle>
              <Button size="sm" onClick={saveScript} disabled={!scriptDirty || updateMutation.isPending}>
                {updateMutation.isPending
                  ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  : <Save className="h-4 w-4 mr-2" />}
                Save
              </Button>
            </CardHeader>
            <CardContent>
              <Textarea
                value={script}
                onChange={(e) => { setScript(e.target.value); setScriptDirty(true); }}
                placeholder="Paste or write your script/rundown here — one story beat per line. Then use Script Match to find footage for each line."
                rows={10}
                className="font-mono text-sm"
              />
              <div className="flex gap-2 mt-4">
                <Link href={`/script-match?project=${id}`}>
                  <Button variant="outline" size="sm">
                    <FileText className="h-4 w-4 mr-2" /> Match Script to Footage
                  </Button>
                </Link>
                <Link href={`/search?project=${id}`}>
                  <Button variant="outline" size="sm">
                    <Search className="h-4 w-4 mr-2" /> Semantic Search
                  </Button>
                </Link>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="assemble" className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Scissors className="h-4 w-4" /> Clip Lists ({clipLists?.length ?? 0})
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {clipLists?.length ? clipLists.map((cl) => (
                  <div key={cl.id} className="flex items-center justify-between bg-muted/50 p-3 rounded">
                    <div className="min-w-0">
                      <div className="font-medium text-sm truncate">{cl.name}</div>
                      <div className="text-xs text-muted-foreground">{cl.clips.length} clips</div>
                    </div>
                    <Link href={`/clips?project=${id}`}>
                      <Button size="sm" variant="ghost">Open</Button>
                    </Link>
                  </div>
                )) : (
                  <p className="text-sm text-muted-foreground py-6 text-center">
                    No clip lists linked yet. Build one from Search results or Script Match, or let the Story Builder assemble one.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <BookOpen className="h-4 w-4" /> Stories ({stories?.length ?? 0})
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {stories?.length ? stories.map((s) => (
                  <div key={s.id} className="flex items-center justify-between bg-muted/50 p-3 rounded">
                    <div className="min-w-0">
                      <div className="font-medium text-sm truncate">{s.title || s.prompt || "Untitled story"}</div>
                      <div className="text-xs text-muted-foreground">{s.asset_ids.length} assets</div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <StatusBadge status={s.status} />
                      <Link href={`/stories?project=${id}`}>
                        <Button size="sm" variant="ghost">Open</Button>
                      </Link>
                    </div>
                  </div>
                )) : (
                  <p className="text-sm text-muted-foreground py-6 text-center">
                    No stories yet. Use the Story Builder to assemble a narrative across assets.
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="cut" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Wand2 className="h-4 w-4" /> Reels & Rough Cuts ({reels?.length ?? 0})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {reels?.length ? reels.map((r) => (
                <div key={r.id} className="flex items-center justify-between bg-muted/50 p-3 rounded">
                  <div className="min-w-0">
                    <div className="font-medium text-sm truncate">{r.prompt}</div>
                    <div className="text-xs text-muted-foreground">
                      {r.clips.length} clips · {r.preset}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <StatusBadge status={r.status} />
                    {r.status === "running" && (
                      <span className="text-xs font-mono text-muted-foreground">{Math.round(r.progress)}%</span>
                    )}
                    <Link href={`/reels?project=${id}`}>
                      <Button size="sm" variant="ghost"><Play className="h-4 w-4" /></Button>
                    </Link>
                  </div>
                </div>
              )) : (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  No reels yet. Create a rough cut from a clip list, or generate a highlight reel from a prompt.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="deliver" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Clapperboard className="h-4 w-4" /> Renders ({renders?.length ?? 0})
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {renders?.length ? renders.map((r) => (
                <div key={r.id} className="flex items-center justify-between bg-muted/50 p-3 rounded">
                  <div className="min-w-0">
                    <div className="font-medium text-sm truncate">{r.label || r.filename || r.media_id}</div>
                    <div className="text-xs text-muted-foreground font-mono">
                      {r.start_time.toFixed(1)}s – {r.end_time.toFixed(1)}s · {r.preset}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <StatusBadge status={r.status} />
                    {r.status === "running" && (
                      <span className="text-xs font-mono text-muted-foreground">{Math.round(r.progress)}%</span>
                    )}
                    <Link href={`/exports?project=${id}`}>
                      <Button size="sm" variant="ghost"><Download className="h-4 w-4" /></Button>
                    </Link>
                  </div>
                </div>
              )) : (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  No renders yet. Render a clip list or a reel to produce deliverable MP4s.
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
