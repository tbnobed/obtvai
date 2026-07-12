import { useState } from "react";
import { useSemanticSearch } from "@workspace/api-client-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Search as SearchIcon, Play } from "lucide-react";
import { Link } from "wouter";

export default function Search() {
  const [query, setQuery] = useState("");
  const searchMutation = useSemanticSearch();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    searchMutation.mutate({ data: { query } });
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      <div className="p-8 border-b border-border bg-card shrink-0">
        <h1 className="text-3xl font-bold tracking-tight mb-6">Semantic Search</h1>
        <form onSubmit={handleSearch} className="flex gap-4 max-w-3xl">
          <Input 
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by speech, visual content, or description..."
            className="flex-1"
          />
          <Button type="submit" disabled={searchMutation.isPending} className="gap-2">
            <SearchIcon className="h-4 w-4" />
            Search
          </Button>
        </form>
      </div>
      
      <div className="flex-1 overflow-y-auto p-8">
        {searchMutation.isPending ? (
          <div className="text-center text-muted-foreground py-10">Searching across the library...</div>
        ) : searchMutation.data ? (
          <div className="space-y-6 max-w-4xl">
            <div className="text-sm text-muted-foreground">
              Found {searchMutation.data.results.length} results in {searchMutation.data.took_ms}ms
            </div>
            {searchMutation.data.results.map((result, i) => (
              <div key={i} className="flex gap-4 p-4 border border-border bg-card rounded-lg hover:border-primary transition-colors">
                <div className="w-48 aspect-video bg-muted rounded shrink-0 relative overflow-hidden">
                  {result.thumbnail_url ? (
                    <img src={`/api/thumbnails/${result.thumbnail_url}`} className="w-full h-full object-cover" />
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center text-muted-foreground/50">No preview</div>
                  )}
                  <Link href={`/library/${result.media_id}?t=${result.start_time}`}>
                    <div className="absolute inset-0 bg-black/0 hover:bg-black/40 flex items-center justify-center opacity-0 hover:opacity-100 transition-all cursor-pointer">
                      <Play className="h-8 w-8 text-white" />
                    </div>
                  </Link>
                </div>
                <div className="flex-1">
                  <div className="flex justify-between items-start mb-2">
                    <Link href={`/library/${result.media_id}?t=${result.start_time}`} className="font-semibold hover:underline">
                      {result.filename}
                    </Link>
                    <div className="text-xs bg-muted px-2 py-1 rounded">Score: {(result.score * 100).toFixed(0)}%</div>
                  </div>
                  <div className="text-xs text-primary mb-2 font-mono">
                    Timecode: {result.start_time.toFixed(1)}s - {result.end_time.toFixed(1)}s
                  </div>
                  {result.snippet && (
                    <p className="text-sm text-muted-foreground italic">"{result.snippet}"</p>
                  )}
                  <div className="mt-2 text-xs text-muted-foreground uppercase tracking-wider">Match: {result.match_type}</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-muted-foreground">
            Enter a search query to explore your media.
          </div>
        )}
      </div>
    </div>
  );
}
