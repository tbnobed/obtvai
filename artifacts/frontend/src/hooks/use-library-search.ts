import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSemanticSearch, getGetSearchHistoryQueryKey } from "@workspace/api-client-react";
import type { SearchQuery, SearchResponse } from "@workspace/api-client-react";
import { buildSearchBody, MIN_QUERY, type LibrarySearchFilters, type SearchScope } from "@/lib/library-search";

/**
 * Runs the committed library search (never per keystroke). Re-runs whenever
 * the committed query, scope or filters change; stale responses from older
 * requests are dropped so the latest request always wins.
 */
export function useLibrarySearch(query: string, scope: SearchScope, filters: LibrarySearchFilters) {
  const queryClient = useQueryClient();
  const search = useSemanticSearch();
  const mutateRef = useRef(search.mutateAsync);
  mutateRef.current = search.mutateAsync;
  const seq = useRef(0);
  const [state, setState] = useState<{ data: SearchResponse | null; loading: boolean; error: boolean; key: string }>(
    { data: null, loading: false, error: false, key: "" },
  );
  const active = query.trim().length >= MIN_QUERY;
  const body = buildSearchBody(query, scope, filters);
  const key = active ? JSON.stringify(body) : "";

  const run = useCallback((k: string) => {
    if (!k) return;
    const id = ++seq.current;
    setState((s) => ({ data: s.key === k ? s.data : null, loading: true, error: false, key: k }));
    mutateRef.current({ data: JSON.parse(k) as SearchQuery })
      .then((data) => {
        if (id !== seq.current) return;
        setState({ data, loading: false, error: false, key: k });
        queryClient.invalidateQueries({ queryKey: getGetSearchHistoryQueryKey() });
      })
      .catch(() => {
        if (id !== seq.current) return;
        setState({ data: null, loading: false, error: true, key: k });
      });
  }, [queryClient]);

  useEffect(() => {
    if (!key) {
      seq.current++; // invalidate any in-flight request
      setState({ data: null, loading: false, error: false, key: "" });
      return;
    }
    run(key);
  }, [key, run]);

  return {
    active,
    data: state.key === key ? state.data : null,
    loading: active && (state.loading || state.key !== key),
    error: active && state.key === key && state.error,
    retry: () => run(key),
  };
}
