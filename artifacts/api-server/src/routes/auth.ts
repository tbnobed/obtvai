import { Router, type IRouter, type Request, type Response, type NextFunction } from "express";
import { randomUUID } from "node:crypto";

export type MockRole = "admin" | "user" | "viewer";

type MockUser = {
  id: string;
  username: string;
  password: string;
  display_name: string | null;
  role: MockRole;
  disabled: boolean;
  created_at: string;
  last_seen: string | null;
};

const created = new Date().toISOString();
const users: MockUser[] = [
  { id: "user-admin", username: "admin", password: "obtv", display_name: "Admin", role: "admin", disabled: false, created_at: created, last_seen: null },
  { id: "user-editor", username: "editor", password: "obtv", display_name: "Editor", role: "user", disabled: false, created_at: created, last_seen: null },
  { id: "user-viewer", username: "viewer", password: "obtv", display_name: "Viewer", role: "viewer", disabled: false, created_at: created, last_seen: null },
];

// token -> user id
const sessions = new Map<string, string>();

const COOKIE_NAME = "obtv_session";

function readToken(req: Request): string | null {
  const header = req.headers.cookie;
  if (!header) return null;
  for (const part of header.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === COOKIE_NAME) return decodeURIComponent(rest.join("="));
  }
  return null;
}

function setSessionCookie(res: Response, token: string | null) {
  // The Replit preview renders inside a cross-site iframe over HTTPS, so the
  // cookie must be SameSite=None + Secure or the browser silently drops it.
  // Production (FastAPI) keeps SameSite=Lax — it is not iframed and runs on
  // plain HTTP inside the LAN.
  const base = `${COOKIE_NAME}=${token ? encodeURIComponent(token) : ""}; Path=/; HttpOnly; SameSite=None; Secure`;
  res.setHeader("Set-Cookie", token ? base : `${base}; Max-Age=0`);
}

function currentUser(req: Request): MockUser | null {
  const token = readToken(req);
  if (!token) return null;
  const userId = sessions.get(token);
  if (!userId) return null;
  const user = users.find((u) => u.id === userId);
  if (!user || user.disabled) return null;
  return user;
}

function sessionUserOut(u: MockUser) {
  return { id: u.id, username: u.username, display_name: u.display_name, role: u.role };
}

function userOut(u: MockUser) {
  return {
    id: u.id,
    username: u.username,
    display_name: u.display_name,
    role: u.role,
    disabled: u.disabled,
    created_at: u.created_at,
    last_seen: u.last_seen,
  };
}

// ── Enforcement middleware (mirrors the production FastAPI middleware) ──────
// Paths seen here are relative to the /api mount (e.g. "/auth/login").

const PUBLIC_PATHS = new Set(["/auth/login", "/healthz"]);

const VIEWER_POST_ALLOWLIST = new Set(["/search", "/search/script-match", "/ai/ask", "/socials/insights", "/auth/logout", "/auth/password"]);

function viewerMayPost(path: string): boolean {
  if (VIEWER_POST_ALLOWLIST.has(path)) return true;
  if (path === "/ai/conversations" || path.startsWith("/ai/conversations/")) return true;
  return false;
}

// ── Audit trail (mirrors the production audit_logs table) ───────────────────

type AuditEntry = {
  id: string; created_at: string; user_id: string | null; username: string | null;
  method: string; path: string; status_code: number; ip: string | null;
};

const auditLog: AuditEntry[] = [];

function recordAudit(entry: Omit<AuditEntry, "id" | "created_at">) {
  auditLog.unshift({ id: randomUUID(), created_at: new Date().toISOString(), ...entry });
  if (auditLog.length > 2000) auditLog.length = 2000;
}

// Seed a few entries so the admin view has content before any actions.
const seedNow = Date.now();
([
  ["admin", "POST", "/api/auth/login", 200],
  ["editor", "POST", "/api/auth/login", 200],
  ["editor", "POST", "/api/media/asset-001/run-stage", 202],
  ["editor", "PATCH", "/api/people/person-001", 200],
  ["admin", "POST", "/api/users", 201],
  ["viewer", "POST", "/api/search", 200],
  ["editor", "DELETE", "/api/clips/clip-002", 204],
] as const).forEach(([username, method, path, status], i) => {
  auditLog.push({
    id: `audit-seed-${i}`,
    created_at: new Date(seedNow - (i + 1) * 47 * 60 * 1000).toISOString(),
    user_id: `user-${username}`, username, method, path, status_code: status,
    ip: "192.168.1.20",
  });
});

export function authMiddleware(req: Request, res: Response, next: NextFunction) {
  const path = req.path.replace(/\/+$/, "") || "/";
  if (PUBLIC_PATHS.has(path)) { next(); return; }

  const user = currentUser(req);
  if (!user) {
    res.status(401).json({ detail: "Not authenticated" });
    return;
  }
  (req as Request & { user?: MockUser }).user = user;
  user.last_seen = new Date().toISOString();

  const method = req.method.toUpperCase();
  const isRead = method === "GET" || method === "HEAD" || method === "OPTIONS";

  if (path === "/users" || path.startsWith("/users/")) {
    if (user.role !== "admin") {
      res.status(403).json({ detail: "Admin only" });
      return;
    }
  } else if (user.role === "viewer" && !isRead && !(method === "POST" && viewerMayPost(path))) {
    res.status(403).json({ detail: "View-only account — ask an admin for edit access" });
    return;
  }
  if (!isRead) {
    res.on("finish", () => recordAudit({
      user_id: user.id, username: user.username, method,
      path: `/api${path}`, status_code: res.statusCode, ip: req.ip ?? null,
    }));
  }
  next();
}

// ── Routes ──────────────────────────────────────────────────────────────────

const router: IRouter = Router();

router.post("/auth/login", (req, res) => {
  const { username, password } = req.body ?? {};
  const name = String(username ?? "").trim().toLowerCase();
  const user = users.find((u) => u.username === name);
  if (!user || user.password !== password || user.disabled) {
    recordAudit({ user_id: null, username: name || null, method: "POST", path: "/api/auth/login", status_code: 401, ip: req.ip ?? null });
    res.status(401).json({ detail: "Invalid username or password" });
    return;
  }
  recordAudit({ user_id: user.id, username: user.username, method: "POST", path: "/api/auth/login", status_code: 200, ip: req.ip ?? null });
  const token = randomUUID();
  sessions.set(token, user.id);
  setSessionCookie(res, token);
  res.json(sessionUserOut(user));
});

router.get("/audit", (req, res) => {
  const me = (req as Request & { user?: MockUser }).user;
  if (!me || me.role !== "admin") { res.status(403).json({ detail: "Admin only" }); return; }
  const q = typeof req.query.q === "string" ? req.query.q.toLowerCase() : null;
  const username = typeof req.query.username === "string" ? req.query.username.trim().toLowerCase() : null;
  const method = typeof req.query.method === "string" ? req.query.method.trim().toUpperCase() : null;
  const limit = Math.min(500, Math.max(1, Number(req.query.limit ?? 100) || 100));
  const offset = Math.max(0, Number(req.query.offset ?? 0) || 0);
  let rows = auditLog;
  if (q) rows = rows.filter((r) => r.path.toLowerCase().includes(q));
  if (username) rows = rows.filter((r) => r.username === username);
  if (method) rows = rows.filter((r) => r.method === method);
  res.json({ total: rows.length, items: rows.slice(offset, offset + limit) });
});

router.post("/auth/logout", (req, res) => {
  const token = readToken(req);
  if (token) sessions.delete(token);
  setSessionCookie(res, null);
  res.status(204).end();
});

router.get("/auth/me", (req, res) => {
  const user = currentUser(req);
  if (!user) { res.status(401).json({ detail: "Not authenticated" }); return; }
  res.json(sessionUserOut(user));
});

router.post("/auth/password", (req, res) => {
  const user = currentUser(req);
  if (!user) { res.status(401).json({ detail: "Not authenticated" }); return; }
  const { current_password, new_password } = req.body ?? {};
  if (user.password !== current_password) {
    res.status(401).json({ detail: "Current password incorrect" });
    return;
  }
  if (typeof new_password !== "string" || new_password.length < 8 || new_password.length > 72) {
    res.status(400).json({ detail: "New password must be at least 8 characters" });
    return;
  }
  user.password = new_password;
  const token = readToken(req);
  for (const [t, uid] of sessions) {
    if (uid === user.id && t !== token) sessions.delete(t);
  }
  res.status(204).end();
});

router.get("/users", (_req, res) => {
  res.json(users.map(userOut));
});

router.post("/users", (req, res) => {
  const { username, password, role, display_name } = req.body ?? {};
  const name = String(username ?? "").trim().toLowerCase();
  if (!/^[a-z0-9._-]{3,50}$/.test(name)) {
    res.status(400).json({ detail: "Username must be 3-50 chars: letters, digits, . _ -" });
    return;
  }
  if (typeof password !== "string" || password.length < 8 || password.length > 72) {
    res.status(400).json({ detail: "Password must be at least 8 characters" });
    return;
  }
  if (!["admin", "user", "viewer"].includes(role)) {
    res.status(400).json({ detail: "Invalid role" });
    return;
  }
  if (users.some((u) => u.username === name)) {
    res.status(409).json({ detail: "Username already exists" });
    return;
  }
  const u: MockUser = {
    id: `user-${randomUUID().slice(0, 8)}`,
    username: name,
    password,
    display_name: display_name ?? null,
    role,
    disabled: false,
    created_at: new Date().toISOString(),
    last_seen: null,
  };
  users.push(u);
  res.status(201).json(userOut(u));
});

router.patch("/users/:id", (req, res) => {
  const me = (req as Request & { user?: MockUser }).user;
  const user = users.find((u) => u.id === req.params.id);
  if (!user) { res.status(404).json({ detail: "User not found" }); return; }
  const { role, display_name, disabled, password } = req.body ?? {};

  const admins = users.filter((u) => u.role === "admin" && !u.disabled);
  const isLastAdmin = user.role === "admin" && !user.disabled && admins.length === 1;
  if (isLastAdmin && ((role && role !== "admin") || disabled === true)) {
    res.status(400).json({ detail: "Cannot demote or disable the last admin" });
    return;
  }
  if (me && me.id === user.id && disabled === true) {
    res.status(400).json({ detail: "Cannot disable your own account" });
    return;
  }
  if (role !== undefined && role !== null) {
    if (!["admin", "user", "viewer"].includes(role)) { res.status(400).json({ detail: "Invalid role" }); return; }
    user.role = role;
  }
  if (display_name !== undefined) user.display_name = display_name;
  if (disabled !== undefined && disabled !== null) user.disabled = disabled;
  if (password !== undefined && password !== null) {
    if (typeof password !== "string" || password.length < 8 || password.length > 72) {
      res.status(400).json({ detail: "Password must be at least 8 characters" });
      return;
    }
    user.password = password;
    for (const [t, uid] of sessions) {
      if (uid === user.id) sessions.delete(t);
    }
  }
  if (user.disabled) {
    for (const [t, uid] of sessions) {
      if (uid === user.id) sessions.delete(t);
    }
  }
  res.json(userOut(user));
});

router.delete("/users/:id", (req, res) => {
  const me = (req as Request & { user?: MockUser }).user;
  const idx = users.findIndex((u) => u.id === req.params.id);
  if (idx === -1) { res.status(404).json({ detail: "User not found" }); return; }
  const user = users[idx]!;
  if (me && me.id === user.id) {
    res.status(400).json({ detail: "Cannot delete your own account" });
    return;
  }
  const admins = users.filter((u) => u.role === "admin" && !u.disabled);
  if (user.role === "admin" && !user.disabled && admins.length === 1) {
    res.status(400).json({ detail: "Cannot delete the last admin" });
    return;
  }
  users.splice(idx, 1);
  for (const [t, uid] of sessions) {
    if (uid === user.id) sessions.delete(t);
  }
  res.status(204).end();
});

export default router;
