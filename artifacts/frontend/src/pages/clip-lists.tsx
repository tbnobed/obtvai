import { useState } from "react";
import { useListClipLists, getListClipListsQueryKey, useExportClipList } from "@workspace/api-client-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Download, Play } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Link } from "wouter";

export default function ClipLists() {
  const { data: lists, isLoading } = useListClipLists({ query: { queryKey: getListClipListsQueryKey() } });
  const exportMutation = useExportClipList();
  
  const [exportData, setExportData] = useState<string | null>(null);

  const handleExport = (listId: string, format: string) => {
    // In a real app we might pass listId to the mutation if supported, 
    // or the export might act on a specific list. Assuming basic behavior.
    // Given the provided spec, we only have useExportClipList() with body {format}.
    exportMutation.mutate({ data: { format } }, {
      onSuccess: (res) => {
        setExportData(res.content);
      }
    });
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Clip Lists</h1>
        <Button disabled>Create New List</Button>
      </div>

      <Dialog open={!!exportData} onOpenChange={(open) => !open && setExportData(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Export Result</DialogTitle>
          </DialogHeader>
          <pre className="bg-muted p-4 rounded-md overflow-x-auto text-xs font-mono max-h-96">
            {exportData}
          </pre>
          <Button onClick={() => navigator.clipboard.writeText(exportData || "")}>Copy to Clipboard</Button>
        </DialogContent>
      </Dialog>

      {isLoading ? (
        <div className="grid gap-6 md:grid-cols-2">
          {[...Array(2)].map((_, i) => <Card key={i} className="animate-pulse h-48 bg-muted" />)}
        </div>
      ) : lists?.length ? (
        <div className="grid gap-6 md:grid-cols-2">
          {lists.map(list => (
            <Card key={list.id} className="flex flex-col">
              <CardHeader className="flex flex-row items-start justify-between">
                <div>
                  <CardTitle>{list.name}</CardTitle>
                  <p className="text-sm text-muted-foreground mt-1">{list.description}</p>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => handleExport(list.id, "edl")}>
                    <Download className="h-4 w-4 mr-2" /> EDL
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="flex-1 flex flex-col">
                <div className="text-sm font-medium mb-3">{list.clips.length} Clips</div>
                <div className="space-y-2 flex-1 overflow-y-auto max-h-48">
                  {list.clips.map((clip, i) => (
                    <div key={clip.id} className="flex items-center justify-between bg-muted/50 p-2 rounded text-sm">
                      <div className="truncate pr-4 flex-1">
                        <span className="text-muted-foreground mr-2">{i+1}.</span>
                        {clip.label || clip.filename || clip.media_id}
                      </div>
                      <div className="flex items-center gap-3 shrink-0">
                        <span className="font-mono text-xs">{clip.start_time}s - {clip.end_time}s</span>
                        <Link href={`/library/${clip.media_id}?t=${clip.start_time}`}>
                          <Button size="icon" variant="ghost" className="h-6 w-6"><Play className="h-3 w-3" /></Button>
                        </Link>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <div className="text-center text-muted-foreground py-20 border border-dashed border-border rounded-lg">
          No clip lists created yet.
        </div>
      )}
    </div>
  );
}
