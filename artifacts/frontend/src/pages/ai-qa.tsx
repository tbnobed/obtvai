import { useState } from "react";
import {
  useAskAI,
  useListConversations, getListConversationsQueryKey,
  useGetConversationMessages, getGetConversationMessagesQueryKey,
  useDeleteConversation,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Send, User, Bot, Plus, MessageSquare, Trash2 } from "lucide-react";
import { Link } from "wouter";
import logoUrl from "@assets/obtv.ai_1783921425806.png";

function formatTimecode(seconds: number): string {
  const total = Math.floor(seconds ?? 0);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

type Message = {
  role: string;
  content: string;
  citations?: any[] | null;
};

export default function AIQA() {
  const [question, setQuestion] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [pendingMessages, setPendingMessages] = useState<Message[]>([]);
  const askMutation = useAskAI();
  const queryClient = useQueryClient();

  const { data: conversations } = useListConversations({
    query: { queryKey: getListConversationsQueryKey() },
  });

  const { data: savedMessages } = useGetConversationMessages(conversationId!, {
    query: {
      enabled: !!conversationId,
      queryKey: getGetConversationMessagesQueryKey(conversationId!),
    },
  });

  // Saved history from the server plus optimistic messages not yet persisted.
  // De-dupe: once the server copy of a pending message arrives, drop the
  // optimistic one so it never renders twice.
  const saved = savedMessages ?? [];
  const savedKeys = new Set(saved.map(m => `${m.role}\u0000${m.content}`));
  const messages: Message[] = [
    ...saved,
    ...pendingMessages.filter(m => !savedKeys.has(`${m.role}\u0000${m.content}`)),
  ];

  const selectConversation = (id: string) => {
    setConversationId(id);
    setPendingMessages([]);
  };

  const newChat = () => {
    setConversationId(null);
    setPendingMessages([]);
  };

  const deleteMutation = useDeleteConversation();
  const deleteConversation = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    deleteMutation.mutate(
      { id },
      {
        onSuccess: () => {
          if (id === conversationId) newChat();
          queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
        },
      }
    );
  };

  const handleAsk = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    const currentQ = question;
    setPendingMessages(prev => [...prev, { role: "user", content: currentQ }]);
    setQuestion("");

    askMutation.mutate(
      { data: { question: currentQ, conversation_id: conversationId ?? undefined } },
      {
        onSuccess: (res) => {
          setPendingMessages(prev => [
            ...prev,
            { role: "assistant", content: res.answer, citations: res.citations },
          ]);
          if (res.conversation_id && res.conversation_id !== conversationId) {
            setConversationId(res.conversation_id);
            // Server history for this conversation now includes the pending
            // messages; clear them once the fresh fetch lands.
            queryClient
              .invalidateQueries({ queryKey: getGetConversationMessagesQueryKey(res.conversation_id) })
              .then(() => setPendingMessages([]));
          } else if (res.conversation_id) {
            queryClient
              .invalidateQueries({ queryKey: getGetConversationMessagesQueryKey(res.conversation_id) })
              .then(() => setPendingMessages([]));
          }
          queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
        },
      }
    );
  };

  return (
    <div className="flex-1 flex h-full overflow-hidden">
      {/* Conversation history sidebar */}
      <div className="w-64 border-r border-border bg-card flex flex-col shrink-0">
        <div className="p-3 border-b border-border">
          <Button variant="outline" size="sm" className="w-full gap-2" onClick={newChat}>
            <Plus className="h-4 w-4" />
            New Chat
          </Button>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {conversations?.map(conv => (
              <div
                key={conv.id}
                role="button"
                tabIndex={0}
                onClick={() => selectConversation(conv.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") selectConversation(conv.id);
                }}
                className={`group w-full text-left p-2 rounded text-sm transition-colors flex gap-2 items-start cursor-pointer ${
                  conv.id === conversationId ? "bg-muted" : "hover:bg-muted/50"
                }`}
              >
                <MessageSquare className="h-4 w-4 mt-0.5 shrink-0 text-muted-foreground" />
                <span className="line-clamp-2 flex-1 min-w-0">{conv.title || "Untitled conversation"}</span>
                <button
                  onClick={(e) => deleteConversation(e, conv.id)}
                  disabled={deleteMutation.isPending}
                  title="Delete chat"
                  className="shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 focus:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
            {!conversations?.length && (
              <div className="text-xs text-muted-foreground text-center py-6">
                No conversations yet
              </div>
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        <div className="p-4 border-b border-border bg-card shrink-0">
          <h1 className="text-xl font-bold tracking-tight">AI Assistant</h1>
        </div>

        <ScrollArea className="flex-1 p-6">
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.length === 0 && (
              <div className="text-center text-muted-foreground py-20">
                <img src={logoUrl} alt="OBTV.AI" className="h-24 w-auto mx-auto mb-6 rounded-lg logo-alive" />
                <p>Ask questions about the content of your media library.</p>
                <p className="text-sm mt-2">Example: "Who mentioned the quarterly report and when?"</p>
              </div>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`flex gap-4 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {msg.role === 'assistant' && <div className="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center shrink-0"><Bot className="h-4 w-4 text-primary" /></div>}

                <div className={`max-w-[80%] rounded-lg p-4 ${msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground'}`}>
                  <div className="whitespace-pre-wrap text-sm">{msg.content}</div>

                  {msg.citations && msg.citations.length > 0 && (
                    <div className="mt-4 pt-4 border-t border-border/50 space-y-2">
                      <div className="text-xs font-semibold mb-2">Sources:</div>
                      {msg.citations.map((cite: any, j: number) => (
                        <Link key={j} href={`/library/${cite.media_id}?t=${cite.start_time}`}>
                          <div className="text-xs bg-background/50 hover:bg-background border border-border/50 p-2 rounded cursor-pointer transition-colors block">
                            <span className="font-mono text-primary mr-2">[{j+1}]</span>
                            {cite.filename} @ {formatTimecode(cite.start_time)}
                          </div>
                        </Link>
                      ))}
                    </div>
                  )}
                </div>

                {msg.role === 'user' && <div className="h-8 w-8 rounded-full bg-secondary flex items-center justify-center shrink-0"><User className="h-4 w-4" /></div>}
              </div>
            ))}
            {askMutation.isPending && (
              <div className="flex gap-4">
                 <div className="h-8 w-8 rounded-full bg-primary/20 flex items-center justify-center"><Bot className="h-4 w-4 text-primary" /></div>
                 <div className="bg-muted p-4 rounded-lg text-sm text-muted-foreground flex items-center gap-2">
                   Analyzing library...
                 </div>
              </div>
            )}
          </div>
        </ScrollArea>

        <div className="p-4 border-t border-border bg-card">
          <form onSubmit={handleAsk} className="max-w-3xl mx-auto flex gap-2">
            <Input
              value={question}
              onChange={e => setQuestion(e.target.value)}
              placeholder="Ask a question..."
              disabled={askMutation.isPending}
            />
            <Button type="submit" disabled={askMutation.isPending || !question.trim()}>
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
