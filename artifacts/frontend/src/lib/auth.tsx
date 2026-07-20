import { createContext, useContext } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  useGetCurrentUser,
  getGetCurrentUserQueryKey,
  useLogout,
} from "@workspace/api-client-react";
import type { SessionUser } from "@workspace/api-client-react";

type AuthContextValue = {
  user: SessionUser | null;
  isLoading: boolean;
};

const AuthContext = createContext<AuthContextValue>({ user: null, isLoading: true });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const query = useGetCurrentUser({
    query: {
      queryKey: getGetCurrentUserQueryKey(),
      retry: false,
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
    },
  });

  const value: AuthContextValue = {
    user: query.isError ? null : (query.data ?? null),
    isLoading: query.isLoading,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

/** True when the signed-in user may modify the library (admin or user role). */
export function useCanEdit() {
  const { user } = useAuth();
  return user != null && user.role !== "viewer";
}

export function useIsAdmin() {
  const { user } = useAuth();
  return user?.role === "admin";
}

export function useLogoutAndReset() {
  const queryClient = useQueryClient();
  const logout = useLogout({
    mutation: {
      onSettled: () => {
        // Same rule as login: never queryClient.clear() while the auth gate's
        // current-user query is mounted — it orphans the subscription and the
        // UI never flips. Remove all other caches, then null out the live
        // current-user entry.
        const userKey = getGetCurrentUserQueryKey();
        queryClient.removeQueries({
          predicate: (q) => q.queryKey[0] !== userKey[0],
        });
        queryClient.getMutationCache().clear();
        queryClient.setQueryData(userKey, null);
      },
    },
  });
  return logout;
}
