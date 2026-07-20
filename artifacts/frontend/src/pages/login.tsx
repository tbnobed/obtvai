import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLogin, getGetCurrentUserQueryKey } from "@workspace/api-client-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import logoUrl from "@assets/obtv.ai_1783921425806.png";

export default function Login() {
  const queryClient = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const login = useLogin({
    mutation: {
      onSuccess: (user) => {
        // Drop everything cached for a previous user before flipping the gate.
        queryClient.clear();
        queryClient.setQueryData(getGetCurrentUserQueryKey(), user);
      },
      onError: (err: unknown) => {
        const status = (err as { status?: number })?.status;
        setError(status === 401 ? "Invalid username or password" : "Login failed — try again");
      },
    },
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    login.mutate({ data: { username: username.trim(), password } });
  };

  return (
    <div className="dark min-h-screen flex flex-col items-center justify-center gap-10 bg-background text-foreground">
      <img src={logoUrl} alt="OBTV.AI" className="h-36 w-auto logo-alive" />
      <div className="w-full max-w-sm p-8 rounded-lg border border-border bg-card space-y-6">
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              data-testid="input-username"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              data-testid="input-password"
            />
          </div>
          {error && (
            <p className="text-sm text-destructive" data-testid="text-login-error">{error}</p>
          )}
          <Button
            type="submit"
            className="w-full"
            disabled={login.isPending || !username.trim() || !password}
            data-testid="button-login"
          >
            {login.isPending ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}
