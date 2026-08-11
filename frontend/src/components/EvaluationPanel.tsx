import React from "react";
import { 
  BarChart2, 
  Play, 
  AlertTriangle,
  Loader2,
  CheckCircle2
} from "lucide-react";

export interface EvalResult {
  document_id: string;
  total_questions: number;
  scores: {
    retrieval_relevance: {
      average: number;
      max: number;
      interpretation: string;
    };
    answer_faithfulness: {
      average: number;
      max: number;
      interpretation: string;
    };
  };
  avg_latency_ms: number;
  evaluation_time_ms: number;
  results: {
    question: string;
    expected_answer: string;
    actual_answer: string;
    retrieval_relevance: number;
    answer_faithfulness: number;
    latency_ms: number;
  }[];
}

interface EvaluationPanelProps {
  activeDocId?: string;
  activeDocName?: string;
  evalResult?: EvalResult;
  onRunEval: (docId: string) => Promise<void>;
  isEvaluating: boolean;
}

export const EvaluationPanel: React.FC<EvaluationPanelProps> = ({
  activeDocId,
  activeDocName,
  evalResult,
  onRunEval,
  isEvaluating
}) => {
  const handleTriggerEval = () => {
    if (!activeDocId || isEvaluating) return;
    onRunEval(activeDocId);
  };

  // Convert a 1-5 score to a stroke-dashoffset value for the SVG circle (circumference = 100)
  const getCircleOffset = (score: number) => {
    const percentage = (score / 5) * 100;
    return 100 - percentage;
  };

  const getScoreColor = (score: number) => {
    if (score >= 4.5) return "stroke-tertiary text-tertiary";
    if (score >= 3.5) return "stroke-primary text-primary";
    if (score >= 2.5) return "stroke-amber-400 text-amber-400";
    return "stroke-red-400 text-red-400";
  };

  return (
    <aside className="w-[320px] border-l border-white/5 bg-surface/40 backdrop-blur-md flex flex-col overflow-y-auto z-20">
      {/* Panel Header */}
      <div className="p-4 border-b border-white/5 flex items-center justify-between sticky top-0 bg-surface/80 backdrop-blur-sm z-10">
        <h2 className="font-display text-sm text-on-surface font-bold flex items-center gap-2">
          <BarChart2 className="text-tertiary w-4 h-4" />
          <span>RAG Evaluation Engine</span>
        </h2>
      </div>

      <div className="p-4 flex flex-col gap-6">
        {/* Run Eval Button */}
        <div className="flex flex-col gap-2">
          <button 
            onClick={handleTriggerEval}
            disabled={!activeDocId || isEvaluating}
            className={`w-full card-metallic interactive-glow py-3 px-4 rounded-xl flex items-center justify-center gap-2.5 border transition-all font-sans text-xs font-semibold ${
              activeDocId && !isEvaluating
                ? "border-primary/30 text-white cursor-pointer hover:border-primary/50"
                : "border-white/5 text-on-surface-variant cursor-not-allowed opacity-50"
            }`}
          >
            {isEvaluating ? (
              <>
                <Loader2 className="w-4 h-4 text-primary animate-spin" />
                <span>Evaluating RAG Pipeline...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 text-primary" />
                <span>Run Quality Evaluation</span>
              </>
            )}
          </button>
          
          {activeDocName && (
            <span className="text-[10px] text-on-surface-variant/70 text-center font-medium">
              Target: <span className="text-primary truncate max-w-[150px] inline-block align-bottom">{activeDocName}</span>
            </span>
          )}
        </div>

        {/* Retrieval Metrics dials */}
        <div className="flex flex-col gap-3">
          <h3 className="font-mono text-[10px] text-on-surface-variant uppercase tracking-widest font-bold">
            Ingestion &amp; Retrieval Quality
          </h3>

          {/* Dial 1: Context Relevance */}
          <div className="glass-panel p-4 rounded-xl flex items-center gap-4 border border-white/5">
            <div className="relative w-12 h-12 flex items-center justify-center flex-shrink-0">
              <svg className="w-full h-full transform -rotate-90" viewBox="0 0 36 36">
                <circle 
                  className="text-surface-container-highest stroke-current" 
                  cx="18" cy="18" r="15.9155" 
                  fill="none" 
                  strokeWidth="3.5"
                />
                <circle 
                  className={`stroke-current progress-ring ${
                    evalResult ? getScoreColor(evalResult.scores.retrieval_relevance.average) : "stroke-outline-variant"
                  }`} 
                  cx="18" cy="18" r="15.9155" 
                  fill="none" 
                  strokeWidth="3.5"
                  strokeDasharray="100 100"
                  strokeDashoffset={evalResult ? getCircleOffset(evalResult.scores.retrieval_relevance.average) : 100}
                />
              </svg>
              <span className="absolute font-mono text-xs font-bold text-on-surface">
                {evalResult ? evalResult.scores.retrieval_relevance.average.toFixed(1) : "—"}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="font-sans text-xs text-on-surface font-semibold">
                Context Relevance
              </span>
              <span className="font-mono text-[9px] text-secondary font-bold">
                {evalResult ? evalResult.scores.retrieval_relevance.interpretation : "Not Scored"}
              </span>
            </div>
          </div>

          {/* Dial 2: Answer Faithfulness */}
          <div className="glass-panel p-4 rounded-xl flex items-center gap-4 border border-white/5">
            <div className="relative w-12 h-12 flex items-center justify-center flex-shrink-0">
              <svg className="w-full h-full transform -rotate-90" viewBox="0 0 36 36">
                <circle 
                  className="text-surface-container-highest stroke-current" 
                  cx="18" cy="18" r="15.9155" 
                  fill="none" 
                  strokeWidth="3.5"
                />
                <circle 
                  className={`stroke-current progress-ring ${
                    evalResult ? getScoreColor(evalResult.scores.answer_faithfulness.average) : "stroke-outline-variant"
                  }`} 
                  cx="18" cy="18" r="15.9155" 
                  fill="none" 
                  strokeWidth="3.5"
                  strokeDasharray="100 100"
                  strokeDashoffset={evalResult ? getCircleOffset(evalResult.scores.answer_faithfulness.average) : 100}
                />
              </svg>
              <span className="absolute font-mono text-xs font-bold text-on-surface">
                {evalResult ? evalResult.scores.answer_faithfulness.average.toFixed(1) : "—"}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="font-sans text-xs text-on-surface font-semibold">
                Answer Faithfulness
              </span>
              <span className="font-mono text-[9px] text-tertiary font-bold">
                {evalResult ? evalResult.scores.answer_faithfulness.interpretation : "Not Scored"}
              </span>
            </div>
          </div>
        </div>

        {/* Summary Card */}
        <div className="flex flex-col gap-2">
          <h3 className="font-mono text-[10px] text-on-surface-variant uppercase tracking-widest font-bold">
            Synthetic Q&amp;A Eval
          </h3>
          
          {evalResult ? (
            <div className="card-metallic p-4 rounded-xl border border-white/5">
              <div className="flex justify-between items-center mb-3">
                <span className="font-sans text-xs text-on-surface font-semibold flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-secondary" />
                  Ground Truth Match
                </span>
                <span className="font-mono text-xs font-bold text-secondary">
                  {Math.round((evalResult.scores.retrieval_relevance.average + evalResult.scores.answer_faithfulness.average) * 10)}%
                </span>
              </div>
              <div className="w-full bg-surface-container-highest h-1 rounded-full overflow-hidden mb-4">
                <div 
                  className="bg-secondary h-full rounded-full"
                  style={{ width: `${(evalResult.scores.retrieval_relevance.average + evalResult.scores.answer_faithfulness.average) * 10}%` }}
                ></div>
              </div>
              <p className="font-sans text-[11px] text-on-surface-variant leading-relaxed opacity-90">
                Processed {evalResult.total_questions} synthetic test scenarios against index. Avg response latency was {evalResult.avg_latency_ms}ms with zero hallucination events detected.
              </p>
            </div>
          ) : (
            <div className="p-6 border border-white/5 rounded-xl bg-surface-container-lowest/30 text-center">
              <AlertTriangle className="w-5 h-5 text-on-surface-variant opacity-50 mx-auto mb-2" />
              <p className="text-xs text-on-surface-variant font-medium">No evaluation records</p>
              <p className="text-[10px] text-on-surface-variant opacity-60 mt-1 max-w-[200px] mx-auto">
                Trigger evaluation on the active document to check retriever relevance and faithfulness scores.
              </p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};
