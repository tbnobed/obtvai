import { useCallback, useMemo, useRef } from "react";
import { useLocation, useSearch } from "wouter";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import {
  useListDeskItems, getListDeskItemsQueryKey,
  useUpdateDeskFavorites, useAppendCollectionAssets,
  getGetEditorialStateQueryKey, getGetEditorialScopeQueryKey,
} from "@workspace/api-client-react";
import type { ListDeskItemsParams } from "@workspace/api-client-react";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/hooks/use-toast";
import { errorMessage } from "@/hooks/use-editorial";
import { patchSearch, readPage } from "@/lib/desk-url";

export type DeskSection = ListDeskItemsParams["section"];
export type DeskParams = Omit<ListDeskItemsParams, "section">;

/** Every desk list key ends with the user id so one person's desk never renders for another. */
export function deskKey(section: DeskSection, params: DeskParams, userId: string | undefined) {
  return [...getListDeskItemsQueryKey({ section, ...params }), userId ?? "anon"] as const;
}

/** Invalidates every desk list (any section, any params) — server pagination means we refetch, never patch. */
export function invalidateDesk(qc: QueryClient) {
  return qc.invalidateQueries({
    predicate: (q) => typeof q.queryKey[0] === "string" && (q.queryKey[0] as string).includes("/desk"),
  });
}

/** Server-paginated desk list. */
export function useDeskList(section: DeskSection, params: DeskParams) {
  const { user } = useAuth();
  return useListDeskItems({ section, ...params }, {
    query: {
      queryKey: deskKey(section, params, user?.id),
      enabled: !!user, staleTime: 15_000, retry: 1,
      placeholderData: (prev, previousQuery) =>
        previousQuery?.queryKey.at(-1) === (user?.id ?? "anon") ? prev : undefined,
    },
  });
}

/** URL-persisted filters. Any filter change resets page to 1. */
export function useUrlFilters<K extends string>(keys: readonly K[]) {
  const search = useSearch();
  const [location, setLocation] = useLocation();
  const values = useMemo(() => {
    const sp = new URLSearchParams(search);
    const out = {} as Record<K | "page", string>;
    for (const k of keys) out[k] = sp.get(k) ?? "";
    out.page = sp.get("page") ?? "";
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);
  const page = readPage(values.page);
  const locRef = useRef(location);
  locRef.current = location;
  const searchRef = useRef(search);
  searchRef.current = search;

  const update = useCallback((patch: Partial<Record<K | "page", string>>) => {
    const qs = patchSearch(searchRef.current, patch as Record<string, string | undefined>);
    setLocation(`${locRef.current}${qs ? `?${qs}` : ""}`, { replace: true });
  }, [setLocation]);

  return { values, page, update, setPage: (p: number) => update({ page: String(p) } as Partial<Record<K | "page", string>>) };
}

/** Bulk desk mutations: favorites add/remove and append assets to a collection. */
export function useDeskBulk() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const favs = useUpdateDeskFavorites();
  const append = useAppendCollectionAssets();

  const refresh = () => {
    qc.invalidateQueries({ queryKey: getGetEditorialStateQueryKey() });
    qc.invalidateQueries({ queryKey: getGetEditorialScopeQueryKey() });
    invalidateDesk(qc);
  };

  const setFavorites = async (ids: string[], operation: "add" | "remove") => {
    try {
      await favs.mutateAsync({ data: { ids, operation } });
      toast({ title: operation === "remove" ? `Removed ${ids.length} from favorites` : `Added ${ids.length} to favorites` });
      return true;
    } catch (e) {
      toast({ variant: "destructive", title: "Couldn't update favorites", description: errorMessage(e, "The server rejected the change.") });
      return false;
    } finally { refresh(); }
  };

  const addToCollection = async (collectionId: string, collectionName: string, mediaIds: string[]) => {
    try {
      await append.mutateAsync({ id: collectionId, data: { media_ids: mediaIds } });
      toast({ title: `Added ${mediaIds.length} to ${collectionName}` });
      return true;
    } catch (e) {
      toast({ variant: "destructive", title: "Couldn't add to collection", description: errorMessage(e, "The server rejected the change.") });
      return false;
    } finally { refresh(); }
  };

  return { setFavorites, addToCollection, pending: favs.isPending || append.isPending };
}
