import { useState, useEffect, useRef } from "react";
import { useAskAI } from "@workspace/api-client-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Send, Bot, User } from "lucide-react";

type ChatMessage = {
  role: string;
  content: string;
  citations?: any[] | null;
};

function formatTimecode(seconds: number): string {
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

export default function AssetChat({ mediaId, onSeek }: { mediaId: string; onSeek: (time: number) => void }) {
  const [question, setQuestion] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const askMutation = useAskAI();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, askMutation.isPending]);

  const handleAsk = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    const currentQ = question;
    setMessages(prev => [...prev, { role: "user", content: currentQ }]);
    setQuestion("");

    askMutation.mutate(
      {
        data: {
          question: currentQ,
          conversation_id: conversationId ?? undefined,
          media_id: mediaId,
        },
      },
      {
        onSuccess: (res) => {
          setMessages(prev => [
            ...prev,
            { role: "assistant", content: res.answer, citations: res.citations },
          ]);
          if (res.conversation_id) setConversationId(res.conversation_id);
        },
        onError: () => {
          setMessages(prev => [
            ...prev,
            { role: "assistant", content: "Sorry, something went wrong answering that. Please try again." },
          ]);
        },
      }
    );
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4">
          {messages.length === 0 && (
            <div className="text-sm text-muted-foreground text-center mt-10 px-4">
              Ask questions about this video.
              <div className="text-xs mt-2">Example: "What are the main arguments made here?"</div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-2 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              {msg.role === "assistant" && (
                <div className="h-6 w-6 rounded-full bg-primary/20 flex items-center justify-center shrink-0 mt-1">
                  <Bot className="h-3.5 w-3.5 text-primary" />
                </div>
              )}
              <div className={`max-w-[85%] rounded-lg p-3 ${msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"}`}>
                <div className="whitespace-pre-wrap text-sm">{msg.content}</div>
                {msg.citations && msg.citations.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-border/50 space-y-1.5">
                    <div className="text-xs font-semibold">Sources:</div>
                    {msg.citations.map((cite: any, j: number) => (
                      <button
                        key={j}
                        type="button"
                        onClick={() => onSeek(cite.start_time)}
                        className="w-full text-left text-xs bg-background/50 hover:bg-background border border-border/50 p-2 rounded cursor-pointer transition-colors"
                      >
                        <span className="font-mono text-primary mr-2">[{j + 1}]</span>
                        {formatTimecode(cite.start_time)}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {msg.role === "user" && (
                <div className="h-6 w-6 rounded-full bg-secondary flex items-center justify-center shrink-0 mt-1">
                  <User className="h-3.5 w-3.5" />
                </div>
              )}
            </div>
          ))}
          {askMutation.isPending && (
            <div className="flex gap-2">
              <div className="h-6 w-6 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
                <Bot className="h-3.5 w-3.5 text-primary" />
              </div>
              <div className="bg-muted p-3 rounded-lg text-sm text-muted-foreground">
                Analyzing video...
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      <div className="p-3 border-t border-border">
        <form onSubmit={handleAsk} className="flex gap-2">
          <Input
            value={question}
            onChange={e => setQuestion(e.target.value)}
            placeholder="Ask about this video..."
            disabled={askMutation.isPending}
          />
          <Button type="submit" size="icon" className="shrink-0" disabled={askMutation.isPending || !question.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </div>
  );
}
