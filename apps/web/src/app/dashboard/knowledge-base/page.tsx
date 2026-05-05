"use client";

/**
 * Story 35.10: Knowledge Base Viewer & Management UI
 *
 * Shows all knowledge the AI has access to, grouped by trust tier.
 * Users can preview content, search/filter, and delete their documents.
 * Critical for trust in a medical AI platform.
 */

import { useState, useEffect, useCallback } from "react";
import {
  BookOpen,
  Search,
  Trash2,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  AlertTriangle,
  Loader2,
  Shield,
  Globe,
  Upload,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import {
  getKnowledgeDocuments,
  getKnowledgeDocumentChunks,
  deleteKnowledgeDocument,
  getKnowledgeStats,
  type KnowledgeDocument,
  type KnowledgeChunkItem,
  type KnowledgeStats,
} from "@/lib/api";
import { MarkdownContent } from "@/components/ui/markdown-content";

// Trust tier colors. Must match the API's KnowledgeChunk.VALID_TIERS frozenset.
// CURATED was dropped in the issue #563 fix -- it was never a real tier in the
// four-tier design; sending it from the dropdown caused a 422 from the regex.
const TIER_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  AUTHORITATIVE: { bg: "bg-emerald-500/20", text: "text-emerald-400", label: "Authoritative" },
  RESEARCHED: { bg: "bg-blue-500/20", text: "text-blue-400", label: "AI Researched" },
  USER_PROVIDED: { bg: "bg-amber-500/20", text: "text-amber-400", label: "User Upload" },
  EXTRACTED: { bg: "bg-purple-500/20", text: "text-purple-400", label: "Extracted" },
};

function TierBadge({ tier }: { tier: string }) {
  const style = TIER_STYLES[tier] || { bg: "bg-slate-500/20", text: "text-slate-400", label: tier };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${style.bg} ${style.text}`}>
      {style.label}
    </span>
  );
}

function DocumentCard({
  doc,
  onDelete,
  onToggleExpand,
  isExpanded,
  chunks,
  loadingChunks,
}: {
  doc: KnowledgeDocument;
  onDelete: () => void;
  onToggleExpand: () => void;
  isExpanded: boolean;
  chunks: KnowledgeChunkItem[];
  loadingChunks: boolean;
}) {
  const isUserOwned = doc.source_type === "ai_research" || doc.source_type === "user_upload";

  return (
    <div className="bg-slate-800/50 border border-slate-700 rounded-lg overflow-hidden">
      <div className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <TierBadge tier={doc.trust_tier} />
              {doc.injection_risk_count > 0 && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-red-500/20 text-red-400">
                  <AlertTriangle className="h-3 w-3" />
                  Risk flagged
                </span>
              )}
            </div>
            <h3 className="font-medium text-white text-sm">{doc.source_name}</h3>
            {doc.source_url && (
              <a
                href={doc.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-slate-500 hover:text-blue-400 flex items-center gap-1 mt-0.5 truncate max-w-md"
              >
                <Globe className="h-3 w-3 flex-shrink-0" />
                {doc.source_url}
                <ExternalLink className="h-3 w-3 flex-shrink-0" />
              </a>
            )}
            <div className="flex gap-3 mt-2 text-xs text-slate-500">
              <span>{doc.chunk_count} chunks</span>
              <span>{(doc.total_content_length / 1024).toFixed(1)} KB</span>
              <span>
                {doc.last_updated
                  ? `Updated: ${new Date(doc.last_updated).toLocaleDateString()}`
                  : `Added: ${new Date(doc.first_created).toLocaleDateString()}`}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2 ml-4">
            <button
              onClick={onToggleExpand}
              className="text-slate-400 hover:text-white transition-colors p-1"
              title="Preview content"
            >
              {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
            {isUserOwned && (
              <button
                onClick={onDelete}
                className="text-slate-500 hover:text-red-400 transition-colors p-1"
                title="Delete document"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Inline chunk preview */}
      {isExpanded && (
        <div className="border-t border-slate-700 bg-slate-900/50 p-4">
          {loadingChunks ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="h-5 w-5 animate-spin text-blue-400" />
              <span className="ml-2 text-sm text-slate-400">Loading content...</span>
            </div>
          ) : chunks.length === 0 ? (
            <p className="text-sm text-slate-500 text-center py-4">No content available</p>
          ) : (
            <div className="space-y-4">
              {chunks.map((chunk, i) => (
                <div key={chunk.id} className="border border-slate-700 rounded p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-slate-500">
                      Chunk {i + 1} of {chunks.length} ({chunk.content_length} chars)
                    </span>
                    {chunk.injection_risk && (
                      <span className="text-xs text-red-400 flex items-center gap-1">
                        <AlertTriangle className="h-3 w-3" />
                        Injection risk
                      </span>
                    )}
                  </div>
                  <div className="prose prose-sm prose-invert max-w-none">
                    <MarkdownContent content={chunk.content} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function KnowledgeBasePage() {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [stats, setStats] = useState<KnowledgeStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Filters
  const [searchText, setSearchText] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [tierFilter, setTierFilter] = useState<string>("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [deleting, setDeleting] = useState<string | null>(null);

  // Expanded documents
  const [expandedDocs, setExpandedDocs] = useState<Set<string>>(new Set());
  const [docChunks, setDocChunks] = useState<Record<string, KnowledgeChunkItem[]>>({});
  const [loadingChunks, setLoadingChunks] = useState<Set<string>>(new Set());

  const docKey = (doc: KnowledgeDocument) => `${doc.source_name}||${doc.source_url || ""}`;

  // Debounce search input (300ms)
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchText), 300);
    return () => clearTimeout(timer);
  }, [searchText]);

  const PAGE_SIZE = 20;

  const loadData = useCallback(async () => {
    setError(null);
    try {
      const [docsData, statsData] = await Promise.all([
        getKnowledgeDocuments({
          trust_tier: tierFilter || undefined,
          search: debouncedSearch || undefined,
          page,
          page_size: PAGE_SIZE,
        }),
        getKnowledgeStats(),
      ]);
      setDocuments(docsData.documents);
      setStats(statsData);
      setTotalPages(Math.max(1, Math.ceil(docsData.total_documents / PAGE_SIZE)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load knowledge base");
    } finally {
      setLoading(false);
    }
  }, [tierFilter, debouncedSearch, page]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleToggleExpand = useCallback((doc: KnowledgeDocument) => {
    const key = docKey(doc);

    setExpandedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });

    // Load chunks if expanding and not already loaded (uses functional update to avoid stale closure)
    setDocChunks((currentChunks) => {
      if (currentChunks[key]) return currentChunks; // Already loaded

      // Check if we're expanding (not collapsing)
      setExpandedDocs((currentExpanded) => {
        if (currentExpanded.has(key) && !currentChunks[key]) {
          setLoadingChunks((prev) => new Set(prev).add(key));
          getKnowledgeDocumentChunks(doc.source_name, doc.source_url)
            .then((data) => {
              setDocChunks((prev) => ({ ...prev, [key]: data.chunks }));
            })
            .catch(() => {
              setDocChunks((prev) => ({ ...prev, [key]: [] }));
            })
            .finally(() => {
              setLoadingChunks((prev) => {
                const next = new Set(prev);
                next.delete(key);
                return next;
              });
            });
        }
        return currentExpanded; // Don't modify, just read
      });

      return currentChunks; // Don't modify, just trigger the check
    });
  }, []);

  const handleDelete = useCallback(async (doc: KnowledgeDocument) => {
    const key = docKey(doc);
    if (deleting) return; // Prevent double-click
    if (!confirm(`Delete "${doc.source_name}"? This will remove all ${doc.chunk_count} chunks from the knowledge base.`)) {
      return;
    }
    setDeleting(key);
    setError(null);
    try {
      const result = await deleteKnowledgeDocument(doc.source_name, doc.source_url);
      setSuccess(`Deleted: ${result.chunks_invalidated} chunks removed`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete document");
    } finally {
      setDeleting(null);
    }
  }, [loadData, deleting]);

  if (loading) {
    return (
      <div className="flex flex-col h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
        <p className="mt-4 text-slate-500 dark:text-slate-400">Loading knowledge base...</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BookOpen className="h-7 w-7 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Knowledge Base</h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm">
              {stats
                ? `${stats.total_documents} documents, ${stats.total_chunks} chunks`
                : "Your AI's clinical knowledge and reference materials"}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadData}
            className="flex items-center gap-2 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
          <button
            disabled
            title="Coming in a future update (Story 35.11)"
            className="flex items-center gap-2 px-3 py-2 bg-slate-700 text-slate-500 text-sm rounded-lg cursor-not-allowed opacity-50"
          >
            <Upload className="h-4 w-4" />
            Upload Document
          </button>
        </div>
      </div>

      {/* Status messages */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-green-500/10 border border-green-500/20 text-green-400 px-4 py-3 rounded-lg text-sm">
          {success}
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3">
        <div className="flex-1 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
          <input
            type="text"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search knowledge base..."
            className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-10 pr-4 py-2 text-sm text-white placeholder-slate-500"
          />
        </div>
        <select
          value={tierFilter}
          onChange={(e) => setTierFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white"
        >
          <option value="">All Tiers</option>
          <option value="AUTHORITATIVE">Authoritative</option>
          <option value="RESEARCHED">AI Researched</option>
          <option value="USER_PROVIDED">User Uploads</option>
          <option value="EXTRACTED">Extracted</option>
        </select>
      </div>

      {/* Tier stats summary */}
      {stats && Object.keys(stats.by_tier).length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {Object.entries(stats.by_tier).map(([tier, count]) => (
            <button
              key={tier}
              onClick={() => setTierFilter(tierFilter === tier ? "" : tier)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs transition-colors ${
                tierFilter === tier
                  ? "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:bg-slate-700"
              }`}
            >
              <Shield className="h-3 w-3" />
              {TIER_STYLES[tier]?.label || tier}: {count} chunks
            </button>
          ))}
        </div>
      )}

      {/* Document list */}
      {documents.length === 0 ? (
        <div className="text-center py-16 bg-slate-800/30 rounded-lg">
          <BookOpen className="h-14 w-14 text-slate-600 mx-auto mb-4" />
          <h2 className="text-lg font-medium text-white mb-2">No Knowledge Yet</h2>
          <p className="text-slate-400 mb-4 max-w-md mx-auto">
            {searchText || tierFilter
              ? "No documents match your search criteria."
              : "Your AI's knowledge base is empty. Configure research sources to start building it."}
          </p>
          {!searchText && !tierFilter && (
            <Link
              href="/dashboard/settings/research-sources"
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors"
            >
              Configure Research Sources
            </Link>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {documents.map((doc) => {
            const key = docKey(doc);
            return (
              <DocumentCard
                key={key}
                doc={doc}
                onDelete={() => handleDelete(doc)}
                onToggleExpand={() => handleToggleExpand(doc)}
                isExpanded={expandedDocs.has(key)}
                chunks={docChunks[key] || []}
                loadingChunks={loadingChunks.has(key)}
              />
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-white text-sm rounded disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="text-sm text-slate-400">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-white text-sm rounded disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
