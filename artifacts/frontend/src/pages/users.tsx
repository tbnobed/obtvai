import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useListUsers,
  useCreateUser,
  useUpdateUser,
  useDeleteUser,
  getListUsersQueryKey,
} from "@workspace/api-client-react";
import type { UserOut } from "@workspace/api-client-react";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/hooks/use-toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { UserPlus, KeyRound, Trash2 } from "lucide-react";

const ROLE_LABELS: Record<string, string> = {
  admin: "Admin",
  user: "User",
  viewer: "View only",
};

function roleBadgeVariant(role: string): "default" | "secondary" | "outline" {
  if (role === "admin") return "default";
  if (role === "user") return "secondary";
  return "outline";
}

function errMessage(err: unknown): string {
  const data = (err as { data?: { detail?: string } })?.data;
  return data?.detail ?? "Request failed";
}

export default function UsersPage() {
  const { user: me } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const usersQuery = useListUsers();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: getListUsersQueryKey() });

  const [createOpen, setCreateOpen] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newRole, setNewRole] = useState<"admin" | "user" | "viewer">("user");

  const [resetTarget, setResetTarget] = useState<UserOut | null>(null);
  const [resetPassword, setResetPassword] = useState("");

  const [deleteTarget, setDeleteTarget] = useState<UserOut | null>(null);

  const createUser = useCreateUser({
    mutation: {
      onSuccess: () => {
        invalidate();
        setCreateOpen(false);
        setNewUsername(""); setNewPassword(""); setNewDisplayName(""); setNewRole("user");
        toast({ title: "User created" });
      },
      onError: (err) => toast({ title: "Could not create user", description: errMessage(err), variant: "destructive" }),
    },
  });

  const updateUser = useUpdateUser({
    mutation: {
      onSuccess: () => invalidate(),
      onError: (err) => {
        invalidate();
        toast({ title: "Could not update user", description: errMessage(err), variant: "destructive" });
      },
    },
  });

  const resetUserPassword = useUpdateUser({
    mutation: {
      onSuccess: () => {
        setResetTarget(null);
        setResetPassword("");
        toast({ title: "Password reset", description: "Their other sessions were signed out." });
      },
      onError: (err) => toast({ title: "Could not reset password", description: errMessage(err), variant: "destructive" }),
    },
  });

  const deleteUser = useDeleteUser({
    mutation: {
      onSuccess: () => {
        invalidate();
        setDeleteTarget(null);
        toast({ title: "User deleted" });
      },
      onError: (err) => toast({ title: "Could not delete user", description: errMessage(err), variant: "destructive" }),
    },
  });

  const users = usersQuery.data ?? [];

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Users</h1>
          <p className="text-sm text-muted-foreground">
            Manage accounts and access levels. Admins manage users and settings; users can do everything else; view-only accounts can browse, search, and ask the AI.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)} data-testid="button-create-user">
          <UserPlus className="h-4 w-4 mr-2" /> New user
        </Button>
      </div>

      {usersQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="rounded-lg border border-border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-muted-foreground">
              <tr>
                <th className="text-left px-4 py-2 font-medium">User</th>
                <th className="text-left px-4 py-2 font-medium">Role</th>
                <th className="text-left px-4 py-2 font-medium">Last seen</th>
                <th className="text-left px-4 py-2 font-medium">Active</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isSelf = me?.id === u.id;
                return (
                  <tr key={u.id} className="border-t border-border" data-testid={`row-user-${u.username}`}>
                    <td className="px-4 py-3">
                      <div className="font-medium">{u.display_name || u.username}</div>
                      <div className="text-xs text-muted-foreground">
                        {u.username}{isSelf ? " (you)" : ""}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Select
                        value={u.role}
                        onValueChange={(role) => updateUser.mutate({ id: u.id, data: { role: role as "admin" | "user" | "viewer" } })}
                        disabled={isSelf}
                      >
                        <SelectTrigger className="w-36 h-8" data-testid={`select-role-${u.username}`}>
                          <SelectValue>
                            <Badge variant={roleBadgeVariant(u.role)}>{ROLE_LABELS[u.role] ?? u.role}</Badge>
                          </SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="admin">Admin</SelectItem>
                          <SelectItem value="user">User</SelectItem>
                          <SelectItem value="viewer">View only</SelectItem>
                        </SelectContent>
                      </Select>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {u.last_seen ? new Date(u.last_seen).toLocaleString() : "Never"}
                    </td>
                    <td className="px-4 py-3">
                      <Switch
                        checked={!u.disabled}
                        onCheckedChange={(checked) => updateUser.mutate({ id: u.id, data: { disabled: !checked } })}
                        disabled={isSelf}
                        data-testid={`switch-active-${u.username}`}
                      />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost" size="sm"
                          onClick={() => { setResetTarget(u); setResetPassword(""); }}
                          data-testid={`button-reset-password-${u.username}`}
                        >
                          <KeyRound className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost" size="sm"
                          className="text-destructive"
                          onClick={() => setDeleteTarget(u)}
                          disabled={isSelf}
                          data-testid={`button-delete-${u.username}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>New user</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="new-username">Username</Label>
              <Input
                id="new-username"
                value={newUsername}
                onChange={(e) => setNewUsername(e.target.value.toLowerCase())}
                placeholder="lowercase letters, digits, . _ -"
                data-testid="input-new-username"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-display-name">Display name (optional)</Label>
              <Input
                id="new-display-name"
                value={newDisplayName}
                onChange={(e) => setNewDisplayName(e.target.value)}
                data-testid="input-new-display-name"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-password">Password</Label>
              <Input
                id="new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="at least 8 characters"
                data-testid="input-new-password"
              />
            </div>
            <div className="space-y-2">
              <Label>Role</Label>
              <Select value={newRole} onValueChange={(v) => setNewRole(v as "admin" | "user" | "viewer")}>
                <SelectTrigger data-testid="select-new-role"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="admin">Admin — manage users and settings</SelectItem>
                  <SelectItem value="user">User — everything except user management</SelectItem>
                  <SelectItem value="viewer">View only — browse, search, ask AI</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button
              onClick={() => createUser.mutate({ data: { username: newUsername.trim(), password: newPassword, role: newRole, display_name: newDisplayName.trim() || null } })}
              disabled={createUser.isPending || newUsername.trim().length < 3 || newPassword.length < 8}
              data-testid="button-confirm-create"
            >
              {createUser.isPending ? "Creating…" : "Create user"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!resetTarget} onOpenChange={(open) => !open && setResetTarget(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Reset password for {resetTarget?.username}</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="reset-password">New password</Label>
            <Input
              id="reset-password"
              type="password"
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
              placeholder="at least 8 characters"
              data-testid="input-reset-password"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setResetTarget(null)}>Cancel</Button>
            <Button
              onClick={() => resetTarget && resetUserPassword.mutate({ id: resetTarget.id, data: { password: resetPassword } })}
              disabled={resetUserPassword.isPending || resetPassword.length < 8}
              data-testid="button-confirm-reset"
            >
              {resetUserPassword.isPending ? "Resetting…" : "Reset password"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Delete {deleteTarget?.username}?</DialogTitle></DialogHeader>
          <p className="text-sm text-muted-foreground">
            This permanently removes the account and signs them out everywhere. Their work (clip lists, projects) is not affected.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button
              variant="destructive"
              onClick={() => deleteTarget && deleteUser.mutate({ id: deleteTarget.id })}
              disabled={deleteUser.isPending}
              data-testid="button-confirm-delete"
            >
              {deleteUser.isPending ? "Deleting…" : "Delete user"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
