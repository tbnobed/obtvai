import { useEffect } from "react";
import { Link, useLocation } from "wouter";
import { 
  LayoutGrid, 
  Film, 
  Search, 
  Activity, 
  MessageSquare, 
  Scissors,
  Users,
  Sparkles,
  Clapperboard,
  FileText,
  Wand2,
  BookOpen,
  FolderKanban
} from "lucide-react";
import logoUrl from "@assets/obtv.ai_1783921425806.png";

export function Layout({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();

  useEffect(() => {
    document.documentElement.classList.add('dark');
  }, []);

  const navItems = [
    { href: "/", label: "Dashboard", icon: LayoutGrid },
    { href: "/projects", label: "Projects", icon: FolderKanban },
    { href: "/library", label: "Media Library", icon: Film },
    { href: "/search", label: "Semantic Search", icon: Search },
    { href: "/people", label: "People", icon: Users },
    { href: "/insights", label: "Insights", icon: Sparkles },
    { href: "/jobs", label: "Processing Pipeline", icon: Activity },
    { href: "/ai", label: "AI Q&A", icon: MessageSquare },
    { href: "/clips", label: "Clip Lists", icon: Scissors },
    { href: "/script-match", label: "Script Match", icon: FileText },
    { href: "/reels", label: "Highlight Reels", icon: Wand2 },
    { href: "/stories", label: "Story Builder", icon: BookOpen },
    { href: "/exports", label: "Exports", icon: Clapperboard },
  ];

  return (
    <div className="flex h-screen w-full bg-background text-foreground overflow-hidden">
      <aside className="w-64 border-r border-border bg-card flex flex-col">
        <div className="h-14 flex items-center px-4 border-b border-border">
          <img src={logoUrl} alt="OBTV.AI" className="h-10 w-auto rounded" />
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-1">
          {navItems.map((item) => {
            const isActive = location === item.href || (item.href !== "/" && location.startsWith(item.href));
            return (
              <Link 
                key={item.href} 
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive 
                    ? "bg-primary/10 text-primary font-medium" 
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <main className="flex-1 flex flex-col overflow-hidden relative app-ambient">
        {children}
      </main>
    </div>
  );
}
