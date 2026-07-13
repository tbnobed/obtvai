import { useListPeople } from "@workspace/api-client-react";
import { Link } from "wouter";
import { Users, User, Mic, Film } from "lucide-react";
import { Badge } from "@/components/ui/badge";

function formatSpeaking(seconds: number) {
  const m = Math.floor(seconds / 60);
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return `${m}m`;
}

export default function People() {
  const { data, isLoading } = useListPeople();

  return (
    <div className="flex-1 p-8 overflow-y-auto flex flex-col">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold tracking-tight">People</h1>
        {data?.length ? (
          <p className="text-sm text-muted-foreground">
            {data.length} {data.length === 1 ? "person" : "people"} identified across the library
          </p>
        ) : null}
      </div>

      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="animate-pulse bg-muted aspect-square rounded-md" />
          ))}
        </div>
      ) : data?.length ? (
        <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {data.map((person) => (
            <Link key={person.id} href={`/people/${person.id}`}>
              <div className="group border border-border bg-card rounded-md overflow-hidden cursor-pointer hover:border-primary transition-colors flex flex-col h-full">
                <div className="aspect-square bg-muted relative">
                  {person.thumbnail_url ? (
                    <img
                      src={`/api/thumbnails/${person.thumbnail_url}`}
                      alt={person.display_name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <User className="h-12 w-12 text-muted-foreground/50" />
                    </div>
                  )}
                  {person.name_source !== "manual" && person.display_name.startsWith("Person ") && (
                    <div className="absolute top-2 right-2">
                      <Badge variant="secondary" className="text-xs">unnamed</Badge>
                    </div>
                  )}
                </div>
                <div className="p-3 flex-1 flex flex-col gap-1.5">
                  <p className="text-sm font-medium truncate" title={person.display_name}>
                    {person.display_name}
                  </p>
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Film className="h-3 w-3" />
                      {person.asset_count} {person.asset_count === 1 ? "asset" : "assets"}
                    </span>
                    <span className="flex items-center gap-1">
                      <Mic className="h-3 w-3" />
                      {formatSpeaking(person.total_speaking_seconds ?? 0)}
                    </span>
                  </div>
                  {person.key_topics?.length ? (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {person.key_topics.slice(0, 2).map((t) => (
                        <Badge key={t} variant="outline" className="text-[10px] px-1.5 py-0 truncate max-w-full">
                          {t}
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
          <Users className="h-12 w-12 mb-4 opacity-50" />
          <p>No people identified yet.</p>
          <p className="text-xs mt-1">People appear here automatically as media is transcribed and analyzed.</p>
        </div>
      )}
    </div>
  );
}
