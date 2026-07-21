import { ThumbsUp, ThumbsDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRateReel, type ReelJob } from "@workspace/api-client-react";

export function ReelRatingButtons({ reel, onRated }: { reel: ReelJob; onRated: () => void }) {
  const rateMutation = useRateReel();
  if (reel.status !== "success") return null;

  const setRating = (value: "up" | "down") => {
    rateMutation.mutate(
      { id: reel.id, data: { rating: reel.rating === value ? null : value } },
      { onSuccess: onRated },
    );
  };

  return (
    <div className="flex items-center gap-0.5" title="Rate this cut — liked reels teach the editor your style">
      <Button
        size="icon"
        variant="ghost"
        className={`h-8 w-8 ${reel.rating === "up" ? "text-green-400" : "text-muted-foreground hover:text-green-400"}`}
        disabled={rateMutation.isPending}
        onClick={() => setRating("up")}
      >
        <ThumbsUp className="h-4 w-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className={`h-8 w-8 ${reel.rating === "down" ? "text-red-400" : "text-muted-foreground hover:text-red-400"}`}
        disabled={rateMutation.isPending}
        onClick={() => setRating("down")}
      >
        <ThumbsDown className="h-4 w-4" />
      </Button>
    </div>
  );
}
