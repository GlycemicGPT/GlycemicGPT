"use client";

/**
 * Daily Briefs / AI Insights Page
 *
 * Story 5.7: AI Insight Card
 * Story 11.3: Wire Daily Briefs Web Delivery
 *
 * Displays a unified feed of AI-generated insights including
 * daily briefs, meal analyses, and correction analyses.
 * Users can filter to show only daily briefs, and can
 * acknowledge or dismiss insights to track review status.
 */

import { useState, useEffect, useCallback } from "react";
import { FileText, Loader2, RefreshCw, Filter } from "lucide-react";
import { AIInsightCard, type InsightData } from "@/components/dashboard";
import { apiFetch, getInsightDetail, getApiBaseUrl, type InsightDetail } from "@/lib/api";

interface InsightsResponse {
  insights: InsightData[];
  total: number;
}

type FilterMode = "all" | "daily_brief";

export default function BriefsPage() {
  const [insights, setInsights] = useState<InsightData[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterMode>("all");

  const fetchInsights = useCallback(async () => {
    try {
      setError(null);
      const response = await apiFetch(`${getApiBaseUrl()}/api/ai/insights?limit=50`);

      if (!response.ok) {
        throw new Error(`Failed to fetch insights: ${response.status}`);
      }

      const data: InsightsResponse = await response.json();
      setInsights(data.insights);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load insights");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInsights();
  }, [fetchInsights]);

  const handleRespond = async (
    analysisType: string,
    analysisId: string,
    response: "acknowledged" | "dismissed",
    reason?: string
  ) => {
    const res = await apiFetch(
      `${getApiBaseUrl()}/api/ai/insights/${analysisType}/${analysisId}/respond`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response, reason }),
      }
    );

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.detail || "Failed to respond");
    }
  };

  const handleFetchDetail = async (
    analysisType: string,
    analysisId: string
  ): Promise<InsightDetail> => {
    return getInsightDetail(analysisType, analysisId);
  };

  const filteredInsights =
    filter === "all"
      ? insights
      : insights.filter((i) => i.analysis_type === filter);

  const briefCount = insights.filter(
    (i) => i.analysis_type === "daily_brief"
  ).length;

  const pendingBriefCount = insights.filter(
    (i) => i.analysis_type === "daily_brief" && i.status === "pending"
  ).length;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">
            {filter === "daily_brief" ? "Daily Briefs" : "AI Insights"}
          </h1>
          <p className="text-slate-400">
            {filter === "daily_brief"
              ? "AI-generated daily summaries of your glucose data"
              : "AI-powered analysis of your glucose patterns"}
          </p>
        </div>
        {!isLoading && (
          <button
            onClick={() => {
              setIsLoading(true);
              fetchInsights();
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 text-slate-300 hover:bg-slate-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Refresh insights"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        )}
      </div>

      {/* Filter tabs */}
      {!isLoading && !error && insights.length > 0 && (
        <div
          className="flex items-center gap-2"
          role="tablist"
          aria-label="Filter insights"
          onKeyDown={(e) => {
            if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
              e.preventDefault();
              setFilter(filter === "all" ? "daily_brief" : "all");
            }
          }}
        >
          <button
            role="tab"
            id="tab-all"
            aria-selected={filter === "all"}
            aria-controls="tabpanel-insights"
            tabIndex={filter === "all" ? 0 : -1}
            onClick={() => setFilter("all")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              filter === "all"
                ? "bg-blue-600 text-white"
                : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
            }`}
          >
            All Insights
            <span className="text-xs opacity-70">({insights.length})</span>
          </button>
          <button
            role="tab"
            id="tab-daily-briefs"
            aria-selected={filter === "daily_brief"}
            aria-controls="tabpanel-insights"
            tabIndex={filter === "daily_brief" ? 0 : -1}
            onClick={() => setFilter("daily_brief")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              filter === "daily_brief"
                ? "bg-blue-600 text-white"
                : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
            }`}
          >
            <Filter className="h-3.5 w-3.5" />
            Daily Briefs
            <span className="text-xs opacity-70">({briefCount})</span>
            {pendingBriefCount > 0 && (
              <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold text-white bg-red-500 rounded-full">
                {pendingBriefCount}
              </span>
            )}
          </button>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <div
          className="bg-slate-900 rounded-xl p-12 border border-slate-800 text-center"
          role="status"
          aria-label="Loading insights"
        >
          <Loader2 className="h-8 w-8 text-blue-400 animate-spin mx-auto mb-3" />
          <p className="text-slate-400">Loading insights...</p>
        </div>
      )}

      {/* Error state */}
      {error && !isLoading && (
        <div
          className="bg-red-500/10 rounded-xl p-6 border border-red-500/20 text-center"
          role="alert"
        >
          <p className="text-red-400">{error}</p>
          <button
            onClick={() => {
              setIsLoading(true);
              fetchInsights();
            }}
            className="mt-3 text-sm text-red-300 hover:text-red-200 underline"
          >
            Try again
          </button>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !error && insights.length === 0 && (
        <div className="bg-slate-900 rounded-xl p-12 border border-slate-800 text-center">
          <div className="flex justify-center mb-4">
            <div className="p-4 bg-blue-500/10 rounded-full">
              <FileText className="h-12 w-12 text-blue-400" />
            </div>
          </div>
          <h2 className="text-xl font-semibold mb-2">No Insights Yet</h2>
          <p className="text-slate-400 max-w-md mx-auto">
            AI insights will appear here once you have enough glucose data.
            Connect your Dexcom CGM and Tandem pump to get started.
          </p>
        </div>
      )}

      {/* Filtered empty state */}
      {!isLoading &&
        !error &&
        insights.length > 0 &&
        filteredInsights.length === 0 && (
          <div
            id="tabpanel-insights"
            role="tabpanel"
            aria-labelledby={filter === "all" ? "tab-all" : "tab-daily-briefs"}
            className="bg-slate-900 rounded-xl p-12 border border-slate-800 text-center"
          >
            <div className="flex justify-center mb-4">
              <div className="p-4 bg-blue-500/10 rounded-full">
                <FileText className="h-12 w-12 text-blue-400" />
              </div>
            </div>
            <h2 className="text-xl font-semibold mb-2">No Daily Briefs Yet</h2>
            <p className="text-slate-400 max-w-md mx-auto">
              Daily briefs will appear here once they are generated.
              Check your brief delivery settings to configure when they are sent.
            </p>
          </div>
        )}

      {/* Insights feed */}
      {!isLoading && !error && filteredInsights.length > 0 && (
        <div
          id="tabpanel-insights"
          role="tabpanel"
          aria-labelledby={filter === "all" ? "tab-all" : "tab-daily-briefs"}
        >
          <p className="text-sm text-slate-500 mb-4">
            Showing {filteredInsights.length}
            {filter !== "all" ? " daily briefs" : ""} of {total} insights
          </p>
          <div className="grid gap-4">
            {filteredInsights.map((insight) => (
              <AIInsightCard
                key={insight.id}
                insight={insight}
                onRespond={handleRespond}
                onFetchDetail={handleFetchDetail}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
