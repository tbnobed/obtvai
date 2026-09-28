import { useCallback, useEffect, useRef, useState } from "react";
import {
  useAskAI,
  useListConversations, getListConversationsQueryKey,
  useGetConversationMessages, getGetConversationMessagesQueryKey,
  useDeleteConversation,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { mergeMessages, pendingPersisted, type ChatMessage } from "@/lib/ai-citations";

type Pending = { convId: string | null; baseline: number; messages: ChatMessage[] };
const EMPTY: Pending = { convId: null, baseline: 0, messages: [] };

/**
 * Conversation state for the archive assistant. The active conversation id is
 * owned by the caller (the library keeps it in the URL) so it survives reloads.
 */
export function useArchiveChat(conversationId: string | null, setConversationId: (id: string | null) => void) {
  const queryClient = useQueryClient();
  const askMutation = useAskAI();
  const deleteMutation = useDeleteConversation();
  const [pending, setPending] = useState<Pending>(EMPTY);
  const [error, setError] = useState<{ question: string; message: string } | null>(null);
  // Bumped whenever the user leaves the current thread; in-flight callbacks
  // from an older generation are ignored instead of clobbering the new view.
  const generation = useRef(0);
  const adoptingId = useRef<string | null>(null);
  const setConvRef = useRef(setConversationId);
  setConvRef.current = setConversationId;

  const conversationsQuery = useListConversations({ query: { queryKey: getListConversationsQueryKey() } });
  const messagesQuery = useGetConversationMessages(conversationId ?? "", {
    query: { enabled: !!conversationId, queryKey: getGetConversationMessagesQueryKey(conversationId ?? "") },
  });
  const saved: ChatMessage[] = conversationId ? (messagesQuery.data ?? []) : [];

  // External conversation change (history pick, back button): drop optimistic state
  // unless it's the id our own ask just adopted.
  useEffect(() => {
    if (adoptingId.current && adoptingId.current === conversationId) { adoptingId.current = null; return; }
    setPending(p => (p.convId === conversationId ? p : EMPTY));
    setError(null);
  }, [conversationId]);

  const visiblePending = pending.convId === conversationId || (!!pending.convId && adoptingId.current === pending.convId)
    ? pending : EMPTY;
  const messages = mergeMessages(saved, visiblePending.messages, visiblePending.baseline);

  // Only discard optimistic messages once persisted copies actually exist.
  useEffect(() => {
    if (!pending.messages.length || askMutation.isPending || !conversationId || pending.convId !== conversationId) return;
    if (messagesQuery.data && pendingPersisted(messagesQuery.data, pending.messages, pending.baseline)) setPending(EMPTY);
  }, [messagesQuery.data, pending, askMutation.isPending, conversationId]);

  const busy = askMutation.isPending;

  const ask = useCallback((raw: string) => {
    const q = raw.trim();
    if (!q || askMutation.isPending) return;
    const gen = generation.current;
    const startConv = conversationId;
    const baseline = startConv ? (messagesQuery.data?.length ?? 0) : 0;
    setError(null);
    setPending(p => ({
      convId: startConv,
      baseline: p.convId === startConv && p.messages.length ? p.baseline : baseline,
      messages: [...(p.convId === startConv ? p.messages : []), { role: "user", content: q }],
    }));
    askMutation.mutate(
      { data: { question: q, conversation_id: startConv ?? undefined } },
      {
        onSuccess: (res) => {
          queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
          if (gen !== generation.current) return;
          const reply: ChatMessage = {
            role: "assistant", content: res.answer, citations: res.citations,
            project_id: res.project_id ?? null, project_name: res.project_name ?? null,
          };
          const newId = res.conversation_id || startConv;
          setPending(p => ({ ...p, convId: newId, messages: [...p.messages, reply] }));
          if (newId && newId !== startConv) {
            adoptingId.current = newId;
            setConvRef.current(newId);
          }
          if (newId) queryClient.invalidateQueries({ queryKey: getGetConversationMessagesQueryKey(newId) });
        },
        onError: (err) => {
          if (gen !== generation.current) return;
          setPending(p => ({ ...p, messages: p.messages.slice(0, -1) }));
          setError({ question: q, message: err instanceof Error && err.message ? err.message : "The assistant couldn't answer. Try again." });
        },
      },
    );
  }, [askMutation, conversationId, messagesQuery.data, queryClient]);

  const leave = (id: string | null) => {
    if (busy) return;
    generation.current += 1;
    setPending(EMPTY);
    setError(null);
    setConvRef.current(id);
  };

  const remove = (id: string) => {
    if (busy) return;
    deleteMutation.mutate({ id }, {
      onSuccess: () => {
        if (id === conversationId) leave(null);
        queryClient.removeQueries({ queryKey: getGetConversationMessagesQueryKey(id) });
        queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
      },
    });
  };

  return {
    conversations: conversationsQuery.data ?? [],
    conversationsLoading: conversationsQuery.isLoading,
    conversationsError: conversationsQuery.isError,
    refetchConversations: conversationsQuery.refetch,
    messages,
    historyLoading: !!conversationId && messagesQuery.isLoading,
    historyError: !!conversationId && messagesQuery.isError,
    refetchHistory: messagesQuery.refetch,
    busy,
    error,
    dismissError: () => setError(null),
    ask,
    newChat: () => leave(null),
    selectConversation: (id: string) => { if (id !== conversationId) leave(id); },
    deleteConversation: remove,
    deleting: deleteMutation.isPending,
  };
}
