import React from "react";

export interface SystemMetrics {
  total_requests: number;
  error_rate: number;
  avg_latency_ms: number;
  cache_hit_rate: number;
  total_tokens_used: number;
  uptime_seconds: number;
}

interface FooterProps {
  systemStatus: "healthy" | "degraded" | "unhealthy";
  metrics?: SystemMetrics;
  version: string;
}

export const Footer: React.FC<FooterProps> = ({
  systemStatus,
  metrics,
  version
}) => {
  const getStatusColor = () => {
    switch (systemStatus) {
      case "healthy":
        return "bg-tertiary";
      case "degraded":
        return "bg-amber-400";
      case "unhealthy":
        return "bg-red-400";
    }
  };

  const getStatusLabel = () => {
    switch (systemStatus) {
      case "healthy":
        return "System Healthy";
      case "degraded":
        return "System Degraded";
      case "unhealthy":
        return "System Offline";
    }
  };

  const formatNumber = (num: number) => {
    if (num >= 1000) {
      return (num / 1000).toFixed(1) + "k";
    }
    return num.toString();
  };

  return (
    <footer className="fixed bottom-0 right-0 w-[calc(100%-280px)] border-t border-white/5 bg-surface-container-lowest flex justify-between items-center px-6 py-1.5 z-50 h-[40px]">
      {/* System Health */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${getStatusColor()} status-pulse`}></span>
          <span className="font-mono text-on-surface-variant text-[11px] font-semibold">
            {getStatusLabel()}
          </span>
        </div>
        <div className="h-3 w-[1px] bg-white/10"></div>
        <span className="font-mono text-on-surface-variant text-[11px] opacity-75">
          {version}
        </span>
      </div>

      {/* RAG Diagnostics */}
      <div className="flex items-center gap-6 font-mono text-[11px] text-on-surface-variant/80">
        {metrics && (
          <>
            <span className="text-tertiary font-semibold">
              Cache Hit Rate: {Math.round(metrics.cache_hit_rate * 100)}%
            </span>
            <span className="text-outline font-semibold">
              Avg. Latency: {Math.round(metrics.avg_latency_ms)}ms
            </span>
            <span className="text-outline font-semibold">
              Total Requests: {formatNumber(metrics.total_requests)}
            </span>
          </>
        )}
        <div className="flex items-center gap-3 ml-2">
          <a 
            href="#status" 
            onClick={(e) => { e.preventDefault(); alert("System components online: agent, security, db (Chroma/PGVector), cache."); }}
            className="text-outline hover:text-on-surface transition-colors cursor-pointer"
          >
            System Status
          </a>
        </div>
      </div>
    </footer>
  );
};
