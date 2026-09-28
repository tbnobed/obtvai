import { useEffect, useRef, useState } from "react";
import { Link } from "wouter";
import { VoiceInput } from "@/components/voice-input";
import { Button } from "@/components/ui/button";
import { ArrowUp, History, Plus, Trash2, X, Sparkles, FolderKanban, RefreshCw, AlertCircle } from "lucide-react";
import { groupCitations } from "@/lib/ai-citations";
import { CitationCard } from "./citation-card";
import { useArchiveChat } from "./use-archive-chat";

const EXAMPLES = [
  "Who talks about the building fund, and when?",
  "Find moments where the choir is on stage",
  "Which interviews mention the youth retreat?",
];

type Props = {
  conversationId: string | null;
  onConversationChange: (id: string | null) => void;
  onClose: () => void;
  /** Question handed over via URL; asked once, then cleared by onInitialQuestionConsumed. */
  initialQuestion?: string | null;
  onInitialQuestionConsumed?: () => void;
};

export function ArchiveChatPanel({ conversationId, onConversationChange, onClose, initialQuestion, onInitialQuestionConsumed }: Props) {
  const chat = useArchiveChat(conversationId, onConversationChange);
  const [question, setQuestion] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const askRef = useRef(chat.ask);
  askRef.current = chat.ask;
  const consumedRef = useRef(onInitialQuestionConsumed);
  consumedRef.current = onInitialQuestionConsumed;
  const handled = useRef<string | null>(null);
  useEffect(() => {
    const q = initialQuestion?.trim();
    if (!q || handled.current === q) return;
    handled.current = q;
    askRef.current(q);
    consumedRef.current?.();
  }, [initialQuestion]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chat.messages.length, chat.busy]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || chat.busy) return;
    chat.ask(question);
    setQuestion("");
  };

  const activeTitle = chat.conversations.find(c => c.id === conversationId)?.title;

  return (
    <div className="flex flex-col h-full min-h-0 bg-card" data-testid="panel-archive-chat">
      <div className="h-12 shrink-0 flex items-center gap-2 px-3 border-b border-border">
        <Sparkles className="h-4 w-4 text-primary shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold leading-tight">Ask the archive</div>
          <div className="text-[11px] text-muted-foreground truncate">{conversationId ? (activeTitle || "Saved conversation") : "New conversation"}</div>
        </div>
        <Button variant="ghost" size="icon" className={`h-8 w-8 ${historyOpen ? "bg-muted" : ""}`} onClick={() => setHistoryOpen(o => !o)} title="Conversation history" aria-label="Conversation history" aria-expanded={historyOpen} data-testid="button-toggle-history">
          <History className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => { chat.newChat(); setHistoryOpen(false); }} disabled={chat.busy} title={chat.busy ? "Wait for the current answer" : "New conversation"} aria-label="New conversation" data-testid="button-new-chat">
          <Plus className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose} title="Close assistant" aria-label="Close assistant" data-testid="button-close-chat">
          <X className="h-4 w-4" />
        </Button>
      </div>

      {historyOpen && (
        <div className="shrink-0 max-h-64 overflow-y-auto border-b border-border bg-background/40 p-2 space-y-0.5" data-testid="list-conversations">
          {chat.conversationsLoading && [0, 1, 2].map(i => <div key={i} className="h-8 rounded bg-muted/60 animate-pulse" />)}
          {chat.conversationsError && (
            <button onClick={() => chat.refetchConversations()} className="w-full text-xs text-muted-foreground py-3 flex items-center justify-center gap-1.5 hover:text-foreground">
              <RefreshCw className="h-3 w-3" /> Couldn't load history — retry
            </button>
          )}
          {!chat.conversationsLoading && !chat.conversationsError && !chat.conversations.length && (
            <div className="text-xs text-muted-foreground text-center py-4">No saved conversations yet.</div>
          )}
          {chat.conversations.map(conv => {
            const active = conv.id === conversationId;
            return (
              <div
                key={conv.id}
                role="button"
                tabIndex={chat.busy ? -1 : 0}
                aria-disabled={chat.busy}
                onClick={() => { if (!chat.busy) { chat.selectConversation(conv.id); setHistoryOpen(false); } }}
                onKeyDown={(e) => { if ((e.key === "Enter" || e.key === " ") && !chat.busy) { chat.selectConversation(conv.id); setHistoryOpen(false); } }}
                className={`group flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors ${chat.busy ? "opacity-50 cursor-not-allowed" : "cursor-pointer"} ${active ? "bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"}`}
                data-testid={`row-conversation-${conv.id}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${active ? "bg-primary" : "bg-border"}`} />
                <span className="flex-1 min-w-0 truncate">{conv.title || "Untitled conversation"}</span>
                <span className="tabular-nums text-[10px] opacity-60">{conv.message_count}</span>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); chat.deleteConversation(conv.id); }}
                  disabled={chat.busy || chat.deleting}
                  title="Delete conversation"
                  aria-label={`Delete ${conv.title || "untitled conversation"}`}
                  className="md:opacity-0 group-hover:opacity-100 focus:opacity-100 text-muted-foreground hover:text-destructive disabled:opacity-30"
                  data-testid={`button-delete-conversation-${conv.id}`}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-3 py-4 space-y-5" aria-live="polite" aria-busy={chat.busy}>
        {chat.historyLoading && (
          <div className="space-y-3">{[0, 1].map(i => <div key={i} className="h-16 rounded-lg bg-muted/50 animate-pulse" />)}</div>
        )}
        {chat.historyError && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-destructive shrink-0" />
            <span className="flex-1">This conversation couldn't be loaded. It may have been deleted.</span>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => chat.refetchHistory()}>Retry</Button>
          </div>
        )}
        {!chat.historyLoading && !chat.historyError && chat.messages.length === 0 && !chat.busy && (
          <div className="pt-6">
            <p className="text-sm font-medium">Find the moment, not just the file.</p>
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              Answers cite exact timecodes in your footage. Click a moment to open the player right there.
            </p>
            <div className="mt-4 space-y-1.5">
              {EXAMPLES.map(ex => (
                <button key={ex} onClick={() => chat.ask(ex)} className="w-full text-left text-xs rounded-md border border-border/70 px-3 py-2 text-muted-foreground hover:text-foreground hover:border-primary/50 hover:bg-primary/5 transition-colors" data-testid="button-example-question">
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {chat.messages.map((msg, i) => {
          if (msg.role === "user") {
            return (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary text-primary-foreground px-3 py-2 text-sm whitespace-pre-wrap" data-testid={`text-user-message-${i}`}>{msg.content}</div>
              </div>
            );
          }
          const groups = groupCitations(msg.citations);
          return (
            <div key={i} className="space-y-2.5" data-testid={`text-assistant-message-${i}`}>
              <div className="text-sm leading-relaxed whitespace-pre-wrap text-foreground/90 border-l-2 border-primary/40 pl-3">{msg.content}</div>
              {msg.project_id && (
                <Link href={`/studio/${msg.project_id}`} className="ml-3 inline-flex items-center gap-2 rounded-md border border-primary/40 bg-primary/10 hover:bg-primary/20 px-3 py-1.5 text-xs font-medium text-primary transition-colors" data-testid="link-open-created-project">
                  <FolderKanban className="h-3.5 w-3.5" />
                  Open project{msg.project_name ? ` “${msg.project_name}”` : ""}
                </Link>
              )}
              {groups.length > 0 && (
                <div className="pl-3 space-y-2">
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                    {groups.length} source{groups.length === 1 ? "" : "s"}
                  </div>
                  {groups.map(g => <CitationCard key={g.mediaId} group={g} />)}
                </div>
              )}
            </div>
          );
        })}

        {chat.busy && (
          <div className="pl-3 border-l-2 border-primary/40 space-y-2" data-testid="status-asking">
            <div className="text-xs text-muted-foreground">Searching transcripts and scenes across the archive…</div>
            <div className="h-3 w-3/4 rounded bg-muted animate-pulse" />
            <div className="h-3 w-1/2 rounded bg-muted animate-pulse" />
          </div>
        )}

        {chat.error && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs space-y-2" data-testid="status-ask-error">
            <div className="flex items-start gap-2"><AlertCircle className="h-4 w-4 text-destructive shrink-0" /><span>{chat.error.message}</span></div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => chat.ask(chat.error!.question)} data-testid="button-retry-ask">Retry</Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => { setQuestion(chat.error!.question); chat.dismissError(); }}>Edit question</Button>
            </div>
          </div>
        )}
      </div>

      <form onSubmit={submit} className="shrink-0 border-t border-border p-3 space-y-1.5">
        <div className="flex items-start gap-2">
          <VoiceInput
            wrapperClassName="flex-1 min-w-0"
            value={question}
            onChange={e => setQuestion(e.target.value)}
            placeholder="Ask about anything said or shown…"
            aria-label="Ask the archive"
            disabled={chat.busy}
            data-testid="input-ask-archive"
          />
          <Button type="submit" size="icon" disabled={chat.busy || !question.trim()} data-testid="button-send-question">
            <ArrowUp className="h-4 w-4" />
          </Button>
        </div>
        <p className="text-[10px] text-muted-foreground">Searches your entire indexed archive — library filters and folders don't narrow answers.</p>
      </form>
    </div>
  );
}
