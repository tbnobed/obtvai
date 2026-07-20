import { useEffect, useState } from "react";
import { Link, useLocation } from "wouter";
import {
  LayoutGrid,
  Film,
  Activity,
  MessageSquare,
  Users,
  Sparkles,
  FolderKanban,
  Wand2,
  Search,
  BarChart3,
  UserCog,
  LogOut,
  KeyRound,
  ChevronUp,
  Eye
} from "lucide-react";
import { useChangePassword } from "@workspace/api-client-react";
import logoUrl from "@assets/obtv.ai_1783921425806.png";
import { useAuth, useIsAdmin, useLogoutAndReset } from "@/lib/auth";
import { useToast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  user: "User",
  viewer: "View only",
};

function ChangePasswordDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { toast } = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");

  const changePassword = useChangePassword({
    mutation: {
      onSuccess: () => {
        onOpenChange(false);
        setCurrent("");
        setNext("");
        toast({ title: "Password changed", description: "Your other sessions were signed out." });
      },
      onError: (err: unknown) => {
        const status = (err as { status?: number })?.status;
        toast({
          title: "Could not change password",
          description: status === 401 ? "Current password is incorrect" : "Request failed",
          variant: "destructive",
        });
      },
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>Change password</DialogTitle></DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="current-password">Current password</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              data-testid="input-current-password"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-password-self">New password</Label>
            <Input
              id="new-password-self"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              placeholder="at least 8 characters"
              data-testid="input-new-password-self"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={() => changePassword.mutate({ data: { current_password: current, new_password: next } })}
            disabled={changePassword.isPending || !current || next.length < 8}
            data-testid="button-confirm-change-password"
          >
            {changePassword.isPending ? "Saving…" : "Change password"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function Layout({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const { user } = useAuth();
  const isAdmin = useIsAdmin();
  const logout = useLogoutAndReset();
  const [passwordOpen, setPasswordOpen] = useState(false);

  useEffect(() => {
    document.documentElement.classList.add('dark');
  }, []);

  const navItems = [
    { href: "/", label: "Dashboard", icon: LayoutGrid },
    { href: "/library", label: "Media Library", icon: Film },
    { href: "/projects", label: "Projects", icon: FolderKanban },
    { href: "/search", label: "Search", icon: Search },
    { href: "/people", label: "People", icon: Users },
    { href: "/graphics", label: "Graphics", icon: Wand2 },
    { href: "/insights", label: "Insights", icon: Sparkles },
    { href: "/ratings", label: "Ratings", icon: BarChart3 },
    { href: "/ai", label: "AI Q&A", icon: MessageSquare },
    { href: "/jobs", label: "Processing Pipeline", icon: Activity },
    ...(isAdmin ? [{ href: "/users", label: "Users", icon: UserCog }] : []),
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
        {user && (
          <div className="p-2 border-t border-border">
            {user.role === "viewer" && (
              <div className="flex items-center gap-2 px-3 py-1.5 mb-1 text-xs text-muted-foreground">
                <Eye className="h-3.5 w-3.5" />
                View-only access
              </div>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  className="w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  data-testid="button-user-menu"
                >
                  <div className="h-7 w-7 rounded-full bg-primary/15 text-primary flex items-center justify-center text-xs font-semibold uppercase">
                    {(user.display_name || user.username).slice(0, 1)}
                  </div>
                  <div className="flex-1 min-w-0 text-left">
                    <div className="truncate text-foreground">{user.display_name || user.username}</div>
                    <div className="text-xs text-muted-foreground">{ROLE_LABELS[user.role] ?? user.role}</div>
                  </div>
                  <ChevronUp className="h-4 w-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuItem onClick={() => setPasswordOpen(true)} data-testid="menu-change-password">
                  <KeyRound className="h-4 w-4 mr-2" /> Change password
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => logout.mutate()} data-testid="menu-logout">
                  <LogOut className="h-4 w-4 mr-2" /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </aside>
      <main className="flex-1 min-w-0 min-h-0 flex flex-col overflow-hidden relative app-ambient">
        {children}
      </main>
      <ChangePasswordDialog open={passwordOpen} onOpenChange={setPasswordOpen} />
    </div>
  );
}
