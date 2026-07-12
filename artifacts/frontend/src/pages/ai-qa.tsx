import { useState } from "react";
import { useAskAI } from "@workspace/api-client-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Send, User, Bot } from "lucide-react";
import { Link } from "wouter";

type Message = {
  role: 'user' | 'assistant';
  content: string;
  citations?: any[];
};

export default function AIQA() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const askMutation = useAskAI();

  const handleAsk = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;

    const currentQ = question;
    setMessages(prev => [...prev, { role: 'user', content: currentQ }]);
    setQuestion("");

    // In a real app we'd track conversation_id, but skipping for simplicity
    askMutation.mutate({ data: { question: currentQ } }, {
      onSuccess: (res) => {
        setMessages(prev => [...prev, { 
          role: 'assistant', 
          content: res.answer,
          citations: res.citations 
        }]);
      }
    });
  };

  return (
    <div className="flex-1 flex flex-col h-full">
      <div className="p-4 border-b border-border bg-card shrink-0">
        <h1 className="text-xl font-bold tracking-tight">AI Assistant</h1>
      </div>

      <ScrollArea className="flex-1 p-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.length === 0 && (
            <div className="text-center text-muted-foreground py-20">
              <Bot className="h-12 w-12 mx-auto mb-4 opacity-20" />
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
                    {msg.citations.map((cite, j) => (
                      <Link key={j} href={`/library/${cite.media_id}?t=${cite.start_time}`}>
                        <div className="text-xs bg-background/50 hover:bg-background border border-border/50 p-2 rounded cursor-pointer transition-colors block">
                          <span className="font-mono text-primary mr-2">[{j+1}]</span>
                          {cite.filename} @ {cite.start_time}s
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
  );
}
