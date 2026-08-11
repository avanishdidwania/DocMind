import { useState, useEffect } from "react";
import { Sidebar } from "./components/Sidebar";
import type { DocumentMetadata } from "./components/Sidebar";
import { ChatWorkspace } from "./components/ChatWorkspace";
import type { Message } from "./components/ChatWorkspace";
import { EvaluationPanel } from "./components/EvaluationPanel";
import type { EvalResult } from "./components/EvaluationPanel";
import { Footer } from "./components/Footer";
import type { SystemMetrics } from "./components/Footer";
import confetti from "canvas-confetti";

const API_BASE = "http://localhost:8000/api";

function App() {
  const [documents, setDocuments] = useState<DocumentMetadata[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  
  const [isGenerating, setIsGenerating] = useState(false);
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState<EvalResult | undefined>(undefined);
  
  const [systemStatus, setSystemStatus] = useState<"healthy" | "degraded" | "unhealthy">("healthy");
  const [metrics, setMetrics] = useState<SystemMetrics | undefined>(undefined);

  // Fetch initial documents and poll health/metrics
  useEffect(() => {
    fetchDocuments();
    fetchDiagnostics();

    const diagnosticsInterval = setInterval(() => {
      fetchDiagnostics();
    }, 10000);

    return () => clearInterval(diagnosticsInterval);
  }, []);

  const fetchDocuments = async () => {
    try {
      const response = await fetch(`${API_BASE}/documents`);
      if (!response.ok) throw new Error("Failed to load documents");
      const data = await response.json();
      setDocuments(data.documents || []);
    } catch (err) {
      console.error("Error fetching documents:", err);
    }
  };

  const fetchDiagnostics = async () => {
    try {
      // Fetch health
      const healthResponse = await fetch(`${API_BASE}/health`);
      if (healthResponse.ok) {
        const healthData = await healthResponse.json();
        setSystemStatus(healthData.status === "healthy" ? "healthy" : "degraded");
      } else {
        setSystemStatus("unhealthy");
      }

      // Fetch metrics
      const metricsResponse = await fetch(`${API_BASE}/metrics`);
      if (metricsResponse.ok) {
        const metricsData = await metricsResponse.json();
        setMetrics({
          total_requests: metricsData.total_requests,
          error_rate: metricsData.error_rate,
          avg_latency_ms: metricsData.avg_latency_ms,
          cache_hit_rate: metricsData.cache_hit_rate,
          total_tokens_used: metricsData.total_tokens_used,
          uptime_seconds: metricsData.uptime_seconds
        });
      }
    } catch (err) {
      console.error("Diagnostics error:", err);
      setSystemStatus("unhealthy");
    }
  };

  // Document Upload callbacks
  const handleUploadStart = () => {
    // Optional: trigger loading visual overlay
  };

  const handleUploadSuccess = (newDoc: DocumentMetadata) => {
    setDocuments((prev) => [newDoc, ...prev]);
    // Automatically select the newly uploaded document
    setSelectedDocIds([newDoc.document_id]);
    
    // Shoot confetti for a nice celebratory feel!
    confetti({
      particleCount: 80,
      spread: 60,
      origin: { y: 0.8, x: 0.1 }
    });
  };

  const handleUploadError = (err: string) => {
    console.error("Upload error callback:", err);
  };

  // Delete Document
  const handleDeleteDoc = async (docId: string) => {
    try {
      const response = await fetch(`${API_BASE}/documents/${docId}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error("Failed to delete document");
      
      // Update UI list
      setDocuments((prev) => prev.filter((d) => d.document_id !== docId));
      setSelectedDocIds((prev) => prev.filter((id) => id !== docId));
      
      // Clear active evaluation result if it belongs to deleted doc
      if (evalResult?.document_id === docId) {
        setEvalResult(undefined);
      }
    } catch (err: any) {
      alert(err.message || "Delete failed");
    }
  };

  // Document Selection
  const handleSelectDoc = (docId: string) => {
    setSelectedDocIds((prev) => {
      if (prev.includes(docId)) {
        return prev.filter((id) => id !== docId);
      } else {
        return [...prev, docId];
      }
    });
  };

  const handleSelectAllDocs = (docIds: string[]) => {
    setSelectedDocIds(docIds);
  };

  // Send message using SSE stream
  const handleSendMessage = async (text: string, mode: "general" | "analytical") => {
    if (isGenerating) return;

    // Create user message state
    const userMsgId = Date.now().toString();
    const userMessage: Message = {
      id: userMsgId,
      role: "user",
      content: text
    };

    // Create assistant message state placeholder
    const assistantMsgId = (Date.now() + 1).toString();
    const assistantMessage: Message = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
      isStreaming: true
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setIsGenerating(true);

    try {
      const body = {
        message: text,
        session_id: sessionId || undefined,
        document_id: selectedDocIds.length === 1 ? selectedDocIds[0] : undefined,
        document_ids: selectedDocIds.length > 1 ? selectedDocIds : undefined,
        mode: mode
      };

      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });

      if (!response.ok) {
        const errJson = await response.json().catch(() => ({}));
        throw new Error(errJson.detail || "Server failed to process stream");
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) throw new Error("No response reader");

      let fullResponseText = "";
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        
        // SSE format sends events starting with "data: " and ending with "\n\n"
        const lines = buffer.split("\n\n");
        // Keep the last partial chunk in buffer
        buffer = lines.pop() || "";

        for (const line of lines) {
          const cleanLine = line.replace(/^data:\s*/, "").trim();
          if (!cleanLine) continue;

          try {
            const dataObj = JSON.parse(cleanLine);
            
            if (dataObj.token) {
              fullResponseText += dataObj.token;
              
              // Update assistant message content live
              setMessages((prev) => 
                prev.map((msg) => 
                  msg.id === assistantMsgId 
                    ? { ...msg, content: fullResponseText }
                    : msg
                )
              );
            }

            if (dataObj.done) {
              const meta = dataObj.metadata || {};
              if (meta.session_id) {
                setSessionId(meta.session_id);
              }
              
              // End streaming status and fill in model/latency diagnostics
              setMessages((prev) => 
                prev.map((msg) => 
                  msg.id === assistantMsgId 
                    ? { 
                        ...msg, 
                        isStreaming: false,
                        latency_ms: meta.latency_ms,
                        model_used: meta.model_used,
                        sources: meta.sources
                      }
                    : msg
                )
              );
            }
          } catch (jsonErr) {
            console.warn("Error parsing stream line JSON:", jsonErr, cleanLine);
          }
        }
      }

      // Finish generating
      setIsGenerating(false);

      // Trigger diagnostics update to see current stats
      fetchDiagnostics();

    } catch (err: any) {
      console.error("Streaming error:", err);
      setMessages((prev) => 
        prev.map((msg) => 
          msg.id === assistantMsgId 
            ? { 
                ...msg, 
                content: err.message || "An error occurred. Check backend server.",
                isStreaming: false
              }
            : msg
        )
      );
      setIsGenerating(false);
    }
  };

  // Run RAG pipeline evaluation
  const handleRunEval = async (docId: string) => {
    if (isEvaluating) return;
    setIsEvaluating(true);

    try {
      const response = await fetch(`${API_BASE}/evaluate/${docId}?n_questions=3`, {
        method: "POST"
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "RAG evaluation failed");
      }

      const result: EvalResult = await response.json();
      setEvalResult(result);
      setIsEvaluating(false);

      // Confetti celebrate on successful evaluation suite run!
      confetti({
        particleCount: 100,
        spread: 80,
        origin: { y: 0.6, x: 0.8 }
      });

    } catch (err: any) {
      alert(err.message || "Evaluation failed");
      setIsEvaluating(false);
    }
  };

  // Find active single document name if exactly one is selected
  const activeSingleDoc = selectedDocIds.length === 1 
    ? documents.find(d => d.document_id === selectedDocIds[0])
    : undefined;

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-on-surface select-none">
      {/* Sidebar - Ingestion Hub */}
      <Sidebar 
        documents={documents}
        selectedDocIds={selectedDocIds}
        onSelectDoc={handleSelectDoc}
        onSelectAllDocs={handleSelectAllDocs}
        onUploadStart={handleUploadStart}
        onUploadSuccess={handleUploadSuccess}
        onUploadError={handleUploadError}
        onDeleteDoc={handleDeleteDoc}
        apiBase={API_BASE}
      />

      {/* Main Workspace - Chat Area */}
      <main className="flex-1 ml-[280px] flex relative h-full">
        <ChatWorkspace 
          messages={messages}
          onSendMessage={handleSendMessage}
          selectedDocIds={selectedDocIds}
          activeDocumentName={activeSingleDoc?.filename}
          inputPlaceholder={
            selectedDocIds.length > 0
              ? `Ask DocMind to analyze ${selectedDocIds.length} document(s)...`
              : "Ask DocMind general questions or upload files to start RAG..."
          }
          isGenerating={isGenerating}
        />

        {/* Right Sidebar - RAG Quality Scoring */}
        <EvaluationPanel 
          activeDocId={activeSingleDoc?.document_id}
          activeDocName={activeSingleDoc?.filename}
          evalResult={evalResult?.document_id === activeSingleDoc?.document_id ? evalResult : undefined}
          onRunEval={handleRunEval}
          isEvaluating={isEvaluating}
        />
      </main>

      {/* Diagnostics Footer status bar */}
      <Footer 
        systemStatus={systemStatus}
        metrics={metrics}
        version="v2.4.1-stable"
      />
    </div>
  );
}

export default App;
