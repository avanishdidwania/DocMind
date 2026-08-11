import React, { useRef, useState } from "react";
import { 
  FileText, 
  UploadCloud, 
  Trash2, 
  BrainCircuit, 
  MessageSquare, 
  Check
} from "lucide-react";

export interface DocumentMetadata {
  document_id: string;
  filename: string;
  page_count: number;
  chunk_count: number;
  total_characters: number;
  processing_time_ms: number;
  created_at: number;
}

interface SidebarProps {
  documents: DocumentMetadata[];
  selectedDocIds: string[];
  onSelectDoc: (docId: string) => void;
  onSelectAllDocs: (docIds: string[]) => void;
  onUploadStart: () => void;
  onUploadSuccess: (doc: DocumentMetadata) => void;
  onUploadError: (err: string) => void;
  onDeleteDoc: (docId: string) => void;
  apiBase: string;
}

export const Sidebar: React.FC<SidebarProps> = ({
  documents,
  selectedDocIds,
  onSelectDoc,
  onSelectAllDocs,
  onUploadStart,
  onUploadSuccess,
  onUploadError,
  onDeleteDoc,
  apiBase
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadingFileName, setUploadingFileName] = useState("");

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      uploadFile(files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      uploadFile(files[0]);
    }
  };

  const uploadFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      onUploadError("Only PDF files are supported");
      alert("Only PDF files are supported");
      return;
    }

    setUploading(true);
    setUploadingFileName(file.name);
    setUploadProgress(10);
    onUploadStart();

    const formData = new FormData();
    formData.append("file", file);

    try {
      // Simulate visual progress increments
      const interval = setInterval(() => {
        setUploadProgress((prev) => {
          if (prev >= 80) {
            clearInterval(interval);
            return 80;
          }
          return prev + 10;
        });
      }, 300);

      const response = await fetch(`${apiBase}/documents/upload`, {
        method: "POST",
        body: formData,
      });

      clearInterval(interval);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to process PDF");
      }

      const result = await response.json();
      setUploadProgress(100);

      // Trigger standard model structure mapping
      const newDoc: DocumentMetadata = {
        document_id: result.document_id,
        filename: result.filename,
        page_count: result.page_count,
        chunk_count: result.chunks_created,
        total_characters: 0, 
        processing_time_ms: result.processing_time_ms,
        created_at: Date.now() / 1000,
      };

      setTimeout(() => {
        setUploading(false);
        setUploadProgress(0);
        setUploadingFileName("");
        onUploadSuccess(newDoc);
      }, 500);

    } catch (err: any) {
      setUploading(false);
      setUploadProgress(0);
      setUploadingFileName("");
      onUploadError(err.message || "Upload failed");
      alert(err.message || "Upload failed");
    }
  };

  return (
    <aside className="fixed left-0 top-0 h-full w-[280px] border-r border-white/5 bg-surface-container-low flex flex-col py-6 px-4 z-50">
      {/* Brand Header */}
      <div className="flex items-center gap-3 mb-8 px-2">
        <div className="w-9 h-9 bg-gradient-to-br from-primary to-tertiary rounded-lg flex items-center justify-center shadow-[0_0_15px_rgba(208,188,255,0.3)]">
          <BrainCircuit className="text-on-primary w-5 h-5" />
        </div>
        <div>
          <h1 className="font-display text-lg font-bold text-primary tracking-tight">
            DocMind
          </h1>
          <p className="font-sans text-[10px] text-on-surface-variant font-semibold uppercase tracking-wider opacity-70">
            Enterprise RAG
          </p>
        </div>
      </div>

      {/* Navigation section */}
      <div className="flex flex-col gap-1 pr-2 pb-4 mb-4 border-b border-white/5">
        <a className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-primary font-semibold border-r-2 border-primary bg-primary/5 cursor-pointer">
          <MessageSquare className="w-4 h-4" />
          <span className="text-sm">RAG Workspace</span>
        </a>
      </div>

      {/* Document Hub Section */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-3 mb-2 flex items-center justify-between text-on-surface-variant">
          <span className="font-mono text-[10px] uppercase tracking-wider font-bold">
            Document Hub
          </span>
          {documents.length > 0 && (
            <button 
              onClick={() => {
                if (selectedDocIds.length === documents.length) {
                  onSelectAllDocs([]);
                } else {
                  onSelectAllDocs(documents.map(d => d.document_id));
                }
              }}
              className="text-[10px] text-primary hover:text-primary-container hover:underline transition-colors font-semibold"
            >
              {selectedDocIds.length === documents.length ? "Deselect All" : "Select All"}
            </button>
          )}
        </div>

        {/* Upload Zone */}
        <div 
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className="mx-2 mt-2 mb-4 border border-dashed border-outline-variant rounded-xl p-4 flex flex-col items-center justify-center bg-surface-container-highest/20 hover:bg-surface-container-highest/40 transition-colors cursor-pointer group"
        >
          <input 
            type="file" 
            ref={fileInputRef} 
            onChange={handleFileChange} 
            accept=".pdf"
            className="hidden" 
          />
          <div className="w-9 h-9 rounded-full bg-surface-container-high flex items-center justify-center mb-2 group-hover:bg-primary/10 transition-colors">
            <UploadCloud className="text-on-surface-variant group-hover:text-primary transition-colors w-4 h-4" />
          </div>
          <span className="font-sans text-xs text-on-surface text-center mb-1 font-medium">
            Upload PDF
          </span>
          <span className="font-mono text-[9px] text-on-surface-variant text-center opacity-70">
            Drag & drop or browse
          </span>

          {/* Progress bar when uploading */}
          {uploading && (
            <div className="w-full mt-3">
              <div className="w-full bg-surface-container-high h-1 rounded-full overflow-hidden">
                <div 
                  className="bg-primary h-full rounded-full transition-all duration-300 shimmer"
                  style={{ width: `${uploadProgress}%` }}
                ></div>
              </div>
              <div className="flex justify-between items-center mt-1.5 font-mono text-[8px] text-on-surface-variant">
                <span className="truncate max-w-[80px]">{uploadingFileName}</span>
                <span>{uploadProgress}%</span>
              </div>
            </div>
          )}
        </div>

        {/* File List */}
        <div className="flex-1 overflow-y-auto px-1 flex flex-col gap-1.5 pb-4">
          {documents.length === 0 ? (
            <div className="text-center py-6 px-3 border border-white/5 rounded-xl bg-surface-container-lowest/30">
              <p className="text-xs text-on-surface-variant font-medium">No documents uploaded</p>
              <p className="text-[10px] text-on-surface-variant opacity-60 mt-1">Upload a PDF to begin chatting</p>
            </div>
          ) : (
            documents.map((doc) => {
              const isSelected = selectedDocIds.includes(doc.document_id);
              return (
                <div 
                  key={doc.document_id}
                  onClick={() => onSelectDoc(doc.document_id)}
                  className={`flex items-center justify-between group px-2.5 py-2 rounded-xl transition-all cursor-pointer border ${
                    isSelected 
                      ? "bg-primary/5 border-primary/20 hover:bg-primary/10" 
                      : "bg-surface-container-lowest/30 border-transparent hover:bg-white/5"
                  }`}
                >
                  <div className="flex items-center gap-2.5 truncate flex-1 mr-2">
                    <div className={`w-5 h-5 rounded flex items-center justify-center flex-shrink-0 ${
                      isSelected ? "bg-primary/25" : "bg-white/5 group-hover:bg-white/10"
                    }`}>
                      {isSelected ? (
                        <Check className="w-3 h-3 text-primary" />
                      ) : (
                        <FileText className="w-3.5 h-3.5 text-error opacity-80" />
                      )}
                    </div>
                    <span className="font-sans text-xs text-on-surface truncate font-medium">
                      {doc.filename}
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="font-mono text-[9px] text-on-surface-variant bg-surface-container-high/60 px-1.5 py-0.5 rounded">
                      {doc.page_count}p
                    </span>
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        if (confirm(`Delete ${doc.filename}?`)) {
                          onDeleteDoc(doc.document_id);
                        }
                      }}
                      className="text-on-surface-variant hover:text-error opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-white/5 transition-all"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </aside>
  );
};
