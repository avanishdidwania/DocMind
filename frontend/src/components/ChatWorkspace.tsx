import React, { useState, useRef, useEffect } from "react";
import { 
  Send, 
  Bot, 
  User, 
  HelpCircle, 
  Clock,
  Cpu,
  FileSearch,
  BookOpen
} from "lucide-react";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  latency_ms?: number;
  model_used?: string;
  sources?: string[];
  pii_masked?: string[];
  security_verdict?: string;
}

interface ChatWorkspaceProps {
  messages: Message[];
  onSendMessage: (text: string, mode: "general" | "analytical") => void;
  selectedDocIds: string[];
  activeDocumentName?: string;
  inputPlaceholder: string;
  isGenerating: boolean;
}

export const ChatWorkspace: React.FC<ChatWorkspaceProps> = ({
  messages,
  onSendMessage,
  selectedDocIds,
  activeDocumentName,
  inputPlaceholder,
  isGenerating
}) => {
  const [inputValue, setInputValue] = useState("");
  const [chatMode, setChatMode] = useState<"general" | "analytical">("general");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom of chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isGenerating]);

  const handleSend = () => {
    if (!inputValue.trim() || isGenerating) return;
    onSendMessage(inputValue, chatMode);
    setInputValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Basic formatter for citations and source cards
  const renderMessageContent = (content: string) => {
    // If the message has markdown style blocks, we format them slightly
    const paragraphs = content.split("\n\n");
    return paragraphs.map((para, i) => {
      // Find code snippet patterns or block quotes
      if (para.startsWith("```") && para.endsWith("```")) {
        const codeText = para.substring(3, para.length - 3).trim();
        return (
          <pre key={i} className="bg-surface-container-lowest/80 border border-outline-variant/30 rounded-lg p-4 font-mono text-xs text-on-surface overflow-x-auto my-3">
            <code>{codeText}</code>
          </pre>
        );
      }

      // Format inline citations like [1], [2] to visual badge pills
      const citationRegex = /\[(\d+)\]/g;
      const parts = para.split(citationRegex);
      if (parts.length > 1) {
        return (
          <p key={i} className="mb-2">
            {parts.map((part, index) => {
              if (index % 2 === 1) {
                // This is a citation number
                return (
                  <span 
                    key={index}
                    className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-secondary/15 text-secondary text-[10px] font-bold mx-1 border border-secondary/20 cursor-help"
                    title={`Source citation #${part}`}
                  >
                    {part}
                  </span>
                );
              }
              return part;
            })}
          </p>
        );
      }

      return (
        <p key={i} className="mb-2 leading-relaxed">
          {para}
        </p>
      );
    });
  };

  return (
    <div className="flex-1 flex flex-col relative h-full">
      {/* Header bar */}
      <header className="fixed top-0 right-0 w-[calc(100%-280px)] border-b border-white/5 bg-surface/80 flex justify-between items-center h-16 px-6 z-40 backdrop-blur-xl">
        <div className="flex items-center gap-3">
          {activeDocumentName ? (
            <div className="flex items-center gap-2 bg-primary/10 border border-primary/20 px-3 py-1 rounded-full text-xs text-primary font-medium">
              <BookOpen className="w-3.5 h-3.5" />
              <span>Target: {activeDocumentName}</span>
            </div>
          ) : selectedDocIds.length > 0 ? (
            <div className="flex items-center gap-2 bg-secondary/10 border border-secondary/20 px-3 py-1 rounded-full text-xs text-secondary font-medium">
              <FileSearch className="w-3.5 h-3.5" />
              <span>Chatting across {selectedDocIds.length} document(s)</span>
            </div>
          ) : (
            <div className="flex items-center gap-2 bg-white/5 border border-white/10 px-3 py-1 rounded-full text-xs text-on-surface-variant font-medium">
              <HelpCircle className="w-3.5 h-3.5" />
              <span>General Assistant Mode (No context selected)</span>
            </div>
          )}
        </div>
        
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-secondary shimmer-anim"></span>
            <span className="text-xs text-on-surface-variant font-mono">Workspace Online</span>
          </div>
          <div className="w-8 h-8 rounded-full overflow-hidden border border-white/10 flex items-center justify-center bg-surface-container-high">
            <User className="w-4 h-4 text-on-surface-variant" />
          </div>
        </div>
      </header>

      {/* Main chat window container */}
      <div className="flex-1 overflow-y-auto pt-24 px-6 pb-36 flex flex-col max-w-4xl mx-auto w-full">
        {messages.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center my-auto py-12 px-6">
            <div className="w-16 h-16 bg-gradient-to-br from-primary/20 to-tertiary/20 border border-primary/30 rounded-2xl flex items-center justify-center mb-4">
              <Bot className="w-8 h-8 text-primary" />
            </div>
            <h2 className="text-2xl font-bold font-display text-white mb-2">Welcome to DocMind</h2>
            <p className="text-sm text-on-surface-variant max-w-md mb-6">
              Ask questions, extract clauses, or compare legal papers. Upload PDFs in the sidebar to feed ground truth documents into the RAG model.
            </p>
            <div className="grid grid-cols-2 gap-3 max-w-lg w-full text-left">
              <div 
                onClick={() => setInputValue("Compare the payment terms across our active contracts.")}
                className="p-3 rounded-xl border border-white/5 bg-surface-container-lowest/30 hover:bg-white/5 cursor-pointer transition-colors"
              >
                <p className="text-xs font-semibold text-primary mb-1">Analytical Comparison</p>
                <p className="text-[11px] text-on-surface-variant truncate">"Compare the payment terms across contracts..."</p>
              </div>
              <div 
                onClick={() => setInputValue("Are there exclusions for gross negligence in the liability clause?")}
                className="p-3 rounded-xl border border-white/5 bg-surface-container-lowest/30 hover:bg-white/5 cursor-pointer transition-colors"
              >
                <p className="text-xs font-semibold text-tertiary mb-1">Contract Intelligence</p>
                <p className="text-[11px] text-on-surface-variant truncate">"Are there exclusions for gross negligence..."</p>
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-6">
            {messages.map((msg) => (
              <div 
                key={msg.id}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {msg.role === "user" ? (
                  <div className="bg-surface-container-high text-on-surface py-3 px-5 rounded-2xl rounded-tr-sm max-w-[80%] text-sm shadow-sm border border-white/5">
                    {msg.content}
                  </div>
                ) : (
                  <div className="flex gap-4 max-w-[90%] w-full">
                    {/* Bot avatar */}
                    <div className="w-8 h-8 rounded-full bg-primary-container flex-shrink-0 flex items-center justify-center border border-primary/30 mt-1">
                      <Bot className="w-4 h-4 text-primary" />
                    </div>
                    {/* Bot message bubble */}
                    <div className="flex flex-col gap-2.5 flex-1">
                      <div className="glass-panel text-on-surface py-4 px-5 rounded-2xl rounded-tl-sm text-sm leading-relaxed shadow-lg border border-white/5">
                        {renderMessageContent(msg.content)}
                        {msg.isStreaming && <span className="caret-blink"></span>}

                        {/* Citation Sources panel */}
                        {msg.sources && msg.sources.length > 0 && (
                          <div className="flex flex-col gap-2 mt-4 pt-4 border-t border-white/5">
                            <span className="text-[10px] uppercase font-mono font-bold tracking-wider text-on-surface-variant">Sources Cited:</span>
                            <div className="flex flex-col gap-1.5">
                              {msg.sources.map((source, index) => (
                                <div 
                                  key={index}
                                  className="flex items-start gap-2 bg-surface-container/50 border border-outline-variant/20 p-2.5 rounded-lg text-xs"
                                >
                                  <div className="w-4 h-4 rounded bg-secondary/15 text-secondary flex items-center justify-center font-bold text-[9px] mt-0.5 border border-secondary/20 flex-shrink-0">
                                    {index + 1}
                                  </div>
                                  <div className="font-mono text-[11px] text-on-surface-variant leading-normal">
                                    {source}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Diagnostic / Metadata bar */}
                      {(msg.model_used || msg.latency_ms) && (
                        <div className="flex items-center gap-3 px-2 font-mono text-[10px] text-on-surface-variant/60">
                          {msg.model_used && (
                            <span className="flex items-center gap-1">
                              <Cpu className="w-3.5 h-3.5 text-primary opacity-80" />
                              <span>Model: {msg.model_used}</span>
                            </span>
                          )}
                          {msg.latency_ms && (
                            <>
                              <span>•</span>
                              <span className="flex items-center gap-1">
                                <Clock className="w-3.5 h-3.5 text-tertiary opacity-80" />
                                <span>Latency: {Math.round(msg.latency_ms)}ms</span>
                              </span>
                            </>
                          )}
                          {msg.security_verdict && (
                            <>
                              <span>•</span>
                              <span className={`px-1.5 py-0.5 rounded text-[9px] ${
                                msg.security_verdict === "safe" ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-red-500/10 text-red-400 border border-red-500/20"
                              }`}>
                                {msg.security_verdict}
                              </span>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input container */}
      <div className="absolute bottom-0 right-0 w-[calc(100%)] px-6 pb-6 bg-gradient-to-t from-background via-background/90 to-transparent pt-4 z-20">
        <div className="max-w-4xl mx-auto w-full">
          <div className="glass-panel p-2 rounded-[24px] border border-outline-variant/40 focus-within:border-primary/50 focus-within:shadow-glow-primary transition-all flex flex-col gap-2 relative overflow-hidden group">
            {/* Mode selection button tags */}
            <div className="flex items-center gap-2 px-3 pt-2">
              <div className="bg-surface-container-high rounded-full p-1 flex items-center">
                <button 
                  onClick={() => setChatMode("general")}
                  className={`px-3 py-1 rounded-full font-sans text-[11px] font-semibold transition-all ${
                    chatMode === "general" 
                      ? "bg-primary/20 text-primary border border-primary/10" 
                      : "text-on-surface-variant hover:text-on-surface border border-transparent"
                  }`}
                >
                  General Q&amp;A
                </button>
                <button 
                  onClick={() => setChatMode("analytical")}
                  className={`px-3 py-1 rounded-full font-sans text-[11px] font-semibold transition-all ${
                    chatMode === "analytical" 
                      ? "bg-tertiary/20 text-tertiary border border-tertiary/10" 
                      : "text-on-surface-variant hover:text-on-surface border border-transparent"
                  }`}
                >
                  Analytical Data
                </button>
              </div>
              
              {/* Highlight message about RAG context */}
              {selectedDocIds.length > 0 && (
                <span className="text-[10px] text-on-surface-variant/70 italic ml-2">
                  Query targets {selectedDocIds.length} document(s)
                </span>
              )}
            </div>

            {/* Input area */}
            <div className="flex items-end gap-2 px-1 pb-1 relative">
              <textarea 
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                className="w-full bg-transparent border-none text-on-surface text-sm placeholder:text-on-surface-variant/50 focus:ring-0 resize-none max-h-32 min-h-[44px] py-3 px-3 outline-none"
                placeholder={inputPlaceholder}
                disabled={isGenerating}
              />
              <div className="flex items-center gap-2 pr-2 pb-1.5 flex-shrink-0">
                <button 
                  onClick={handleSend}
                  disabled={!inputValue.trim() || isGenerating}
                  className={`p-2.5 rounded-full transition-all cursor-pointer ${
                    inputValue.trim() && !isGenerating
                      ? "bg-primary text-white hover:bg-primary-container shadow-glow-primary"
                      : "bg-white/5 text-on-surface-variant cursor-not-allowed"
                  }`}
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* subtle animated background glow */}
            <div className="absolute inset-0 bg-gradient-to-r from-primary/5 via-tertiary/5 to-transparent opacity-0 group-focus-within:opacity-100 transition-opacity pointer-events-none -z-10"></div>
          </div>
          <div className="text-center mt-2">
            <span className="text-[10px] text-on-surface-variant/50 font-semibold uppercase tracking-wider">
              AI generated content may be inaccurate. Verify important information.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
