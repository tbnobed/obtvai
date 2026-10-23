import { Star, Bookmark } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useEditorialActions, useEditorialState } from "@/hooks/use-editorial";

export function FavoriteButton({ mediaId, compact }: { mediaId: string; compact?: boolean }) {
  const { data, isError } = useEditorialState();
  const actions = useEditorialActions();
  const on = !!data?.me.favorite_media_ids.includes(mediaId);
  return (
    <Button
      variant="outline" size="sm" type="button"
      className={`gap-1.5 shrink-0 ${on ? "border-amber-400/50 text-amber-300 hover:text-amber-200" : ""}`}
      disabled={!data}
      title={isError ? "Desk unavailable" : on ? "Remove from favorites" : "Add to favorites (My Desk)"}
      aria-pressed={on}
      onClick={(e) => { e.stopPropagation(); actions.toggleFavorite(mediaId); }}
      data-testid="button-toggle-favorite"
    >
      <Star className={`h-4 w-4 ${on ? "fill-current" : ""}`} />
      {!compact && <span>{on ? "Favorited" : "Favorite"}</span>}
    </Button>
  );
}

/** Saving a project only pins it to your desk — it does not make you the owner. */
export function SaveProjectButton({ projectId, compact }: { projectId: string; compact?: boolean }) {
  const { data } = useEditorialState();
  const actions = useEditorialActions();
  const on = !!data?.me.saved_project_ids.includes(projectId);
  return (
    <Button
      variant={compact ? "ghost" : "outline"} size="sm" type="button"
      className={`gap-1.5 shrink-0 ${compact ? "h-7 w-7 p-0" : ""} ${on ? "text-primary" : "text-muted-foreground"}`}
      disabled={!data}
      title={on ? "Remove from My Desk" : "Save to My Desk"}
      aria-label={on ? "Remove from My Desk" : "Save to My Desk"}
      aria-pressed={on}
      onClick={(e) => { e.stopPropagation(); actions.toggleSavedProject(projectId); }}
      data-testid={`button-save-project-${projectId}`}
    >
      <Bookmark className={`h-4 w-4 ${on ? "fill-current" : ""}`} />
      {!compact && <span>{on ? "On my desk" : "Save to desk"}</span>}
    </Button>
  );
}
