import { useRef, useState } from "react";
import {
  useEnrollPerson,
  useMergePerson,
  getListPeopleQueryKey,
  getGetCoAppearancesQueryKey,
} from "@workspace/api-client-react";
import type { PersonEnrollResult } from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { ImagePlus, User, Film, Loader2 } from "lucide-react";

function extractErrorMessage(err: unknown): string {
  if (typeof err === "object" && err !== null) {
    const data = (err as { data?: unknown }).data;
    if (typeof data === "object" && data !== null) {
      const detail = (data as { detail?: unknown }).detail;
      if (typeof detail === "string" && detail.trim()) return detail;
    }
    const message = (err as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return "Enrollment failed — the API server did not respond.";
}

export default function EnrollPersonDialog() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [result, setResult] = useState<PersonEnrollResult | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [merging, setMerging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const enroll = useEnrollPerson();
  const merge = useMergePerson();
  const queryClient = useQueryClient();

  const reset = () => {
    setName("");
    setFile(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setResult(null);
    setSelected(new Set());
    setError(null);
    setMerging(false);
  };

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: getListPeopleQueryKey() });
    queryClient.invalidateQueries({ queryKey: getGetCoAppearancesQueryKey() });
  };

  const handleOpenChange = (next: boolean) => {
    if (!next && (enroll.isPending || merging)) return;
    setOpen(next);
    if (!next) {
      if (result) invalidate();
      reset();
    }
  };

  const handleFile = (f: File | null) => {
    setFile(f);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(f ? URL.createObjectURL(f) : null);
    setError(null);
  };

  const handleEnroll = () => {
    if (!file || !name.trim() || enroll.isPending) return;
    setError(null);
    enroll.mutate(
      { data: { photo: file, display_name: name.trim() } },
      {
        onSuccess: (res) => {
          setResult(res);
          setSelected(new Set(res.matches.filter((m) => m.strong).map((m) => m.person_id)));
          invalidate();
        },
        onError: (err: unknown) => {
          setError(extractErrorMessage(err));
        },
      }
    );
  };

  const toggleSelected = (personId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(personId)) next.delete(personId);
      else next.add(personId);
      return next;
    });
  };

  const handleMerge = async () => {
    if (!result || selected.size === 0 || merging) return;
    setMerging(true);
    setError(null);
    let failures = 0;
    for (const sourceId of selected) {
      try {
        await merge.mutateAsync({
          id: result.person.id,
          data: { source_person_id: sourceId },
        });
      } catch {
        failures += 1;
      }
    }
    setMerging(false);
    invalidate();
    if (failures > 0) {
      setError(`${failures} merge${failures === 1 ? "" : "s"} failed — check the API server.`);
    } else {
      setOpen(false);
      reset();
    }
  };

  return (
    <>
      <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setOpen(true)}>
        <ImagePlus className="h-4 w-4" />
        Add from Photo
      </Button>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-md">
          {!result ? (
            <>
              <DialogHeader>
                <DialogTitle>Add a person from a photo</DialogTitle>
                <DialogDescription>
                  Upload a clear photo of their face. The system stores its signature, finds
                  look-alike people already in the library, and auto-names them in future footage.
                </DialogDescription>
              </DialogHeader>
              <div className="flex flex-col gap-4">
                <div
                  className="border border-dashed border-border rounded-md p-4 flex items-center gap-4 cursor-pointer hover:border-primary transition-colors"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {previewUrl ? (
                    <img src={previewUrl} alt="Preview" className="h-20 w-20 rounded-md object-cover" />
                  ) : (
                    <div className="h-20 w-20 rounded-md bg-muted flex items-center justify-center">
                      <User className="h-8 w-8 text-muted-foreground/50" />
                    </div>
                  )}
                  <div className="text-sm text-muted-foreground">
                    {file ? file.name : "Click to choose a photo (JPG/PNG, one clear face)"}
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
                  />
                </div>
                <Input
                  placeholder="Person's name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleEnroll();
                  }}
                />
                {error && <p className="text-sm text-destructive">{error}</p>}
                <Button
                  onClick={handleEnroll}
                  disabled={!file || !name.trim() || enroll.isPending}
                  className="gap-1.5"
                >
                  {enroll.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                  {enroll.isPending ? "Analyzing face..." : "Detect & Search Library"}
                </Button>
              </div>
            </>
          ) : (
            <>
              <DialogHeader>
                <DialogTitle>{result.person.display_name} added</DialogTitle>
                <DialogDescription>
                  {result.matches.length > 0
                    ? "These existing people look like the photo. Merge the ones that are the same person — their appearances move over and duplicates disappear."
                    : "No look-alikes found in the library yet. New footage of this person will be named automatically once processed."}
                </DialogDescription>
              </DialogHeader>
              {result.matches.length > 0 && (
                <div className="flex flex-col gap-2 max-h-72 overflow-y-auto">
                  {result.matches.map((m) => (
                    <label
                      key={m.person_id}
                      className="flex items-center gap-3 border border-border rounded-md p-2 cursor-pointer hover:border-primary transition-colors"
                    >
                      <Checkbox
                        checked={selected.has(m.person_id)}
                        onCheckedChange={() => toggleSelected(m.person_id)}
                      />
                      {m.thumbnail_url ? (
                        <img
                          src={`/api/thumbnails/${m.thumbnail_url}`}
                          alt={m.display_name}
                          className="h-10 w-10 rounded-md object-cover"
                        />
                      ) : (
                        <div className="h-10 w-10 rounded-md bg-muted flex items-center justify-center shrink-0">
                          <User className="h-5 w-5 text-muted-foreground/50" />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{m.display_name}</p>
                        <p className="text-xs text-muted-foreground flex items-center gap-1">
                          <Film className="h-3 w-3" />
                          {m.asset_count} {m.asset_count === 1 ? "video" : "videos"}
                        </p>
                      </div>
                      <span
                        className={`text-xs font-medium shrink-0 ${m.strong ? "text-primary" : "text-muted-foreground"}`}
                      >
                        {Math.round(m.similarity * 100)}% match
                      </span>
                    </label>
                  ))}
                </div>
              )}
              {error && <p className="text-sm text-destructive">{error}</p>}
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => handleOpenChange(false)}
                  disabled={merging}
                >
                  Done
                </Button>
                {result.matches.length > 0 && (
                  <Button onClick={handleMerge} disabled={selected.size === 0 || merging} className="gap-1.5">
                    {merging && <Loader2 className="h-4 w-4 animate-spin" />}
                    {merging
                      ? "Merging..."
                      : `Merge ${selected.size} into ${result.person.display_name}`}
                  </Button>
                )}
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
