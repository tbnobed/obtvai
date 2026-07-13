import { useState } from "react";
import { useScriptMatch, useCreateClipList } from "@workspace/api-client-react";
import type { ScriptMatchResponse, SearchResult } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { FileText, Play, ListPlus, Check } from "lucide-react";
import { Link, useLocation } from "wouter";

function fmtTime(s: number) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

type Selected = { line: string; match: SearchResult };

export default function ScriptMatch() {
  const [, navigate] = useLocation();
  const [script, setScript] = useState("");
  const [result, setResult] = useState<ScriptMatchResponse | null>(null);
  const [selected, setSelected] = useState<Map<string, Selected>>(new Map());
  const [saveOpen, setSaveOpen] = useState(false);
  const [listName, setListName] = useState("");

  const matchMutation = useScriptMatch();
  const createListMutation = useCreateClipList();

  const runMatch = () => {
    setSelected(new Map());
    matchMutation.mutate(
      { data: { script } },
      { onSuccess: (res) => setResult(res) },
    );
  };

  const keyFor = (line: string, m: SearchResult) => `${line}|${m.media_id}|${m.start_time}`;

  const toggle = (line: string, m: SearchResult) => {
    setSelected((prev) => {
      const next = new Map(prev);
      const k = keyFor(line, m);
      if (next.has(k)) next.delete(k);
      else next.set(k, { line, match: m });
      return next;
    });
  };

  const saveAsClipList = () => {
    createListMutation.mutate(
      {
        data: {
          name: listName,
          description: "Created from script match",
          clips: Array.from(selected.values()).map(({ line, match }) => ({
            media_id: match.media_id,
            start_time: match.start_time,
            end_time: match.end_time,
            label: line.length > 80 ? `${line.slice(0, 77)}...` : line,
          })),
        },
      },
      {
        onSuccess: () => {
          setSaveOpen(false);
          navigate("/clips");
        },
      },
    );
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">Script Match</h1>
        <p className="text-muted-foreground mt-1">
          Paste a script or rundown — each line is matched against the library so you can assemble a clip list
        </p>
      </div>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save as Clip List</DialogTitle>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="list-name">List name</Label>
            <Input id="list-name" value={listName} onChange={(e) => setListName(e.target.value)} placeholder="e.g. Evening bulletin — housing story" />
            <p className="text-sm text-muted-foreground">{selected.size} clip{selected.size === 1 ? "" : "s"} selected</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveOpen(false)}>Cancel</Button>
            <Button onClick={saveAsClipList} disabled={!listName.trim() || createListMutation.isPending}>
              {createListMutation.isPending ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Card className="mb-6">
        <CardContent className="pt-6 space-y-3">
          <Textarea
            value={script}
            onChange={(e) => setScript(e.target.value)}
            rows={8}
            placeholder={"One story beat per line, e.g.\n\nSarah Chen explains the local AI infrastructure initiative\nCouncil vote on the affordable housing measure\nBusiness owners react to construction downtown"}
            className="font-mono text-sm"
          />
          <div className="flex justify-end">
            <Button onClick={runMatch} disabled={!script.trim() || matchMutation.isPending}>
              <FileText className="h-4 w-4 mr-2" />
              {matchMutation.isPending ? "Matching..." : "Match Script"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {result && (
        <>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-muted-foreground">
              {result.lines.length} line{result.lines.length === 1 ? "" : "s"} matched in {result.took_ms}ms
            </p>
            <Button size="sm" onClick={() => { setListName(""); setSaveOpen(true); }} disabled={selected.size === 0}>
              <ListPlus className="h-4 w-4 mr-2" /> Save {selected.size || ""} as Clip List
            </Button>
          </div>

          <div className="space-y-6">
            {result.lines.map((lineResult, li) => (
              <div key={li}>
                <div className="flex items-baseline gap-2 mb-2">
                  <span className="text-xs font-mono text-muted-foreground shrink-0">{li + 1}.</span>
                  <p className="font-medium">{lineResult.line}</p>
                </div>
                {lineResult.matches.length ? (
                  <div className="space-y-2 ml-6">
                    {lineResult.matches.map((m, mi) => {
                      const isSelected = selected.has(keyFor(lineResult.line, m));
                      return (
                        <Card key={mi} className={isSelected ? "border-primary" : ""}>
                          <CardContent className="py-3">
                            <div className="flex items-center gap-3">
                              <Checkbox
                                checked={isSelected}
                                onCheckedChange={() => toggle(lineResult.line, m)}
                              />
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-medium truncate">{m.filename}</span>
                                  <Badge variant="outline" className="font-mono text-xs">
                                    {fmtTime(m.start_time)} – {fmtTime(m.end_time)}
                                  </Badge>
                                  <Badge variant="outline" className="text-xs">
                                    {Math.round(m.score * 100)}%
                                  </Badge>
                                </div>
                                {m.snippet && (
                                  <p className="text-sm text-muted-foreground mt-1 line-clamp-2">"{m.snippet}"</p>
                                )}
                              </div>
                              <Link href={`/library/${m.media_id}?t=${Math.floor(m.start_time)}`}>
                                <Button size="icon" variant="ghost" className="h-8 w-8 shrink-0">
                                  <Play className="h-4 w-4" />
                                </Button>
                              </Link>
                              {isSelected && <Check className="h-4 w-4 text-primary shrink-0" />}
                            </div>
                          </CardContent>
                        </Card>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground ml-6">No matches in the library.</p>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
