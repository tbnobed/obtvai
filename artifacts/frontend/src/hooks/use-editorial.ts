import { useCallback, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation } from "wouter";
import {
  useGetEditorialState, getGetEditorialStateQueryKey,
  useGetEditorialScope, getGetEditorialScopeQueryKey,
  useUpdateEditorialMe, useRecordRecentMedia,
  useCreateWorkspace, useUpdateWorkspace, useDeleteWorkspace,
  useCreateCollection, useUpdateCollection, useDeleteCollection,
  getListMediaQueryKey, getGetEditorialCollectionQueryKey,
} from "@workspace/api-client-react";
import type {
  EditorialState, EditorialMeUpdate, WorkspaceInput, CollectionInput, Collection, Workspace,
} from "@workspace/api-client-react";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/hooks/use-toast";
import { toggleId } from "@/lib/editorial";

function invalidateDeskLists(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ predicate: (q) => typeof q.queryKey[0] === "string" && (q.queryKey[0] as string).includes("/desk") });
}

export function errorMessage(e: unknown, fallback: string): string {
  const err = e as { data?: { detail?: unknown; error?: unknown }; message?: string } | null;
  const detail = err?.data?.detail ?? err?.data?.error;
  if (typeof detail === "string" && detail) return detail;
  if (err?.message) return err.message;
  return fallback;
}

/** Cache keys carry the user id so one person's desk never renders for another. */
function stateKey(userId: string | undefined, lite: boolean) {
  return [...getGetEditorialStateQueryKey(), userId ?? "anon", lite ? "lite" : "full"] as const;
}

/** On /desk and its subroutes the state is fetched without full collections (they can be huge). */
export function isDeskPath(path: string): boolean {
  return path === "/desk" || path.startsWith("/desk/");
}

function useStateMode() {
  const [location] = useLocation();
  return isDeskPath(location);
}

export function useEditorialState() {
  const { user } = useAuth();
  const lite = useStateMode();
  const key = stateKey(user?.id, lite);
  const params = lite ? { include_collections: false } : undefined;
  const q = useGetEditorialState(params, {
    query: { queryKey: key, enabled: !!user, staleTime: 30_000, retry: 1 },
  });
  return { ...q, key, collectionsLoaded: !lite };
}

/** Resolved scope (media ids + timed items). null media_ids = All Library. */
export function useEditorialScope(workspaceId: string | null, collectionId: string | null) {
  const { user } = useAuth();
  const params = { workspace_id: workspaceId ?? undefined, collection_id: collectionId ?? undefined };
  const scoped = !!(workspaceId || collectionId);
  return useGetEditorialScope(params, {
    query: {
      queryKey: [...getGetEditorialScopeQueryKey(params), user?.id ?? "anon"],
      enabled: !!user && scoped,
      staleTime: 15_000,
    },
  });
}

/** All editorial mutations, with cache patching + scoped invalidation and visible errors. */
export function useEditorialActions() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { user } = useAuth();
  const lite = useStateMode();
  const key = stateKey(user?.id, lite);

  const updateMe = useUpdateEditorialMe();
  const recordRecent = useRecordRecentMedia();
  const createWs = useCreateWorkspace();
  const updateWs = useUpdateWorkspace();
  const deleteWs = useDeleteWorkspace();
  const createCol = useCreateCollection();
  const updateCol = useUpdateCollection();
  const deleteCol = useDeleteCollection();

  const refs = useRef({ updateMe, recordRecent, createWs, updateWs, deleteWs, createCol, updateCol, deleteCol });
  refs.current = { updateMe, recordRecent, createWs, updateWs, deleteWs, createCol, updateCol, deleteCol };

  const toastRef = useRef(toast);
  toastRef.current = toast;

  const getState = () => queryClient.getQueryData<EditorialState>(key);
  const patchState = (fn: (s: EditorialState) => EditorialState) =>
    queryClient.setQueryData<EditorialState>(key, (old) => (old ? fn(old) : old));

  const invalidateScope = () => {
    queryClient.invalidateQueries({ queryKey: getGetEditorialStateQueryKey() });
    queryClient.invalidateQueries({ queryKey: getGetEditorialScopeQueryKey() });
    queryClient.invalidateQueries({ queryKey: getListMediaQueryKey() });
    invalidateDeskLists(queryClient);
  };

  const fail = (title: string) => (e: unknown) =>
    toast({ variant: "destructive", title, description: errorMessage(e, "The server rejected the change.") });

  const patchMe = (data: EditorialMeUpdate, failTitle: string, onDone?: () => void) => {
    const prev = getState();
    patchState((s) => ({ ...s, me: { ...s.me, ...data } as EditorialState["me"] }));
    refs.current.updateMe.mutate({ data }, {
      onSuccess: (me) => {
        patchState((s) => ({ ...s, me }));
        queryClient.invalidateQueries({ queryKey: getGetEditorialStateQueryKey() });
        invalidateDeskLists(queryClient);
        onDone?.();
      },
      onError: (e) => { if (prev) queryClient.setQueryData(key, prev); fail(failTitle)(e); },
    });
  };

  const toggleFavorite = (mediaId: string) => {
    const s = getState();
    if (!s) return;
    patchMe({ favorite_media_ids: toggleId(s.me.favorite_media_ids, mediaId) }, "Couldn't update favorites");
  };

  const toggleSavedProject = (projectId: string) => {
    const s = getState();
    if (!s) return;
    patchMe({ saved_project_ids: toggleId(s.me.saved_project_ids, projectId) }, "Couldn't update saved projects");
  };

  const rememberWorkspace = (workspaceId: string | null) => {
    const s = getState();
    if (!s || s.me.workspace_id === workspaceId) return;
    const ids = workspaceId && !s.me.workspace_ids.includes(workspaceId) ? [...s.me.workspace_ids, workspaceId] : s.me.workspace_ids;
    patchMe({ workspace_id: workspaceId, workspace_ids: ids }, "Couldn't remember your workspace");
  };

  const recordRecentView = useCallback((mediaId: string) => {
    refs.current.recordRecent.mutate({ data: { media_id: mediaId } }, {
      onSuccess: () => { queryClient.invalidateQueries({ queryKey: getGetEditorialStateQueryKey() }); invalidateDeskLists(queryClient); },
      // Non-blocking: playback continues, but the user learns My Desk won't list it.
      onError: (e) => toastRef.current({
        title: "Not added to Recently viewed",
        description: errorMessage(e, "My Desk couldn't record this view. Playback is unaffected."),
      }),
    });
  }, [queryClient]);

  const saveWorkspace = (id: string | null, data: WorkspaceInput, onDone?: (w: Workspace) => void) => {
    const opts = {
      onSuccess: (w: Workspace) => {
        patchState((s) => ({ ...s, workspaces: id ? s.workspaces.map((x) => (x.id === w.id ? w : x)) : [...s.workspaces, w] }));
        invalidateScope();
        onDone?.(w);
      },
      onError: fail(id ? "Couldn't update workspace" : "Couldn't create workspace"),
    };
    if (id) refs.current.updateWs.mutate({ id, data }, opts);
    else refs.current.createWs.mutate({ data }, opts);
  };

  const removeWorkspace = (id: string, onDone?: () => void) => {
    refs.current.deleteWs.mutate({ id }, {
      onSuccess: () => {
        patchState((s) => ({ ...s, workspaces: s.workspaces.filter((w) => w.id !== id) }));
        invalidateScope();
        onDone?.();
      },
      onError: fail("Couldn't delete workspace"),
    });
  };

  const saveCollection = (id: string | null, data: CollectionInput, onDone?: (c: Collection) => void, failTitle?: string) => {
    const opts = {
      onSuccess: (c: Collection) => {
        // Lite (desk) state has no collections; never inject a partial list there.
        if (!lite) patchState((s) => ({ ...s, collections: id ? s.collections.map((x) => (x.id === c.id ? c : x)) : [...s.collections, c] }));
        queryClient.setQueryData(getGetEditorialCollectionQueryKey(c.id), c);
        invalidateScope();
        onDone?.(c);
      },
      onError: fail(failTitle ?? (id ? "Couldn't update collection" : "Couldn't create collection")),
    };
    if (id) refs.current.updateCol.mutate({ id, data }, opts);
    else refs.current.createCol.mutate({ data }, opts);
  };

  const removeCollection = (id: string, onDone?: () => void) => {
    refs.current.deleteCol.mutate({ id }, {
      onSuccess: () => {
        if (!lite) patchState((s) => ({ ...s, collections: s.collections.filter((c) => c.id !== id) }));
        queryClient.removeQueries({ queryKey: getGetEditorialCollectionQueryKey(id) });
        invalidateScope();
        onDone?.();
      },
      onError: fail("Couldn't delete collection"),
    });
  };

  return {
    toggleFavorite, toggleSavedProject, rememberWorkspace, recordRecentView,
    saveWorkspace, removeWorkspace, saveCollection, removeCollection,
    pending: {
      workspace: createWs.isPending || updateWs.isPending,
      deleteWorkspace: deleteWs.isPending,
      collection: createCol.isPending || updateCol.isPending,
      deleteCollection: deleteCol.isPending,
    },
  };
}

export function collectionInput(c: Collection, patch: Partial<CollectionInput> = {}): CollectionInput {
  return {
    name: c.name, description: c.description, workspace_id: c.workspace_id ?? null,
    kind: c.kind, visibility: c.visibility, rules: c.rules ?? {}, items: c.items, ...patch,
  };
}

export function workspaceInput(w: Workspace, patch: Partial<WorkspaceInput> = {}): WorkspaceInput {
  return { name: w.name, description: w.description, rules: w.rules ?? {}, media_ids: w.media_ids, ...patch };
}
