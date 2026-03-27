"use client";

/**
 * Story 35.12: AI Research Sources Settings
 *
 * Allows users to configure URLs that the AI researches for clinical
 * documentation specific to their devices, insulin, and CGM.
 */

import { useState, useEffect, useCallback } from "react";
import { BookOpen, Plus, Trash2, RefreshCw, Loader2, ArrowLeft, Lightbulb } from "lucide-react";
import Link from "next/link";
import {
  getResearchSources,
  addResearchSource,
  deleteResearchSource,
  triggerResearch,
  getResearchSuggestions,
  type ResearchSource,
  type ResearchSuggestion,
} from "@/lib/api";

export default function ResearchSourcesPage() {
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [suggestions, setSuggestions] = useState<ResearchSuggestion[]>([]);
  const [basedOn, setBasedOn] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [researching, setResearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Add source form
  const [showAddForm, setShowAddForm] = useState(false);
  const [newUrl, setNewUrl] = useState("");
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState("");
  const [adding, setAdding] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const [sourcesData, suggestionsData] = await Promise.all([
        getResearchSources(),
        getResearchSuggestions(),
      ]);
      setSources(sourcesData.sources);
      setSuggestions(suggestionsData.suggestions);
      setBasedOn(suggestionsData.based_on);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleAddSource = useCallback(async (url: string, name: string, category?: string) => {
    setAdding(true);
    setError(null);
    try {
      await addResearchSource(url, name, category);
      setSuccess(`Added: ${name}`);
      setShowAddForm(false);
      setNewUrl("");
      setNewName("");
      setNewCategory("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add source");
    } finally {
      setAdding(false);
    }
  }, [loadData]);

  const handleDelete = useCallback(async (sourceId: string, sourceName: string) => {
    setError(null);
    try {
      await deleteResearchSource(sourceId);
      setSuccess(`Removed: ${sourceName}`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete source");
    }
  }, [loadData]);

  const handleResearch = useCallback(async () => {
    setResearching(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await triggerResearch();
      const parts = [];
      if (result.new > 0) parts.push(`${result.new} new`);
      if (result.updated > 0) parts.push(`${result.updated} updated`);
      if (result.unchanged > 0) parts.push(`${result.unchanged} unchanged`);
      if (result.errors > 0) parts.push(`${result.errors} errors`);
      setSuccess(`Research complete: ${parts.join(", ")}`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Research failed");
    } finally {
      setResearching(false);
    }
  }, [loadData]);

  if (loading) {
    return (
      <div className="flex flex-col h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
        <p className="mt-4 text-slate-500 dark:text-slate-400">Loading research sources...</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/dashboard/settings" className="text-slate-400 hover:text-white transition-colors">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <BookOpen className="h-6 w-6 text-blue-400" />
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">AI Research Sources</h1>
          <p className="text-slate-500 dark:text-slate-400">
            The AI researches these URLs for clinical documentation about your devices and medications
          </p>
        </div>
      </div>

      {/* Status messages */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 px-4 py-3 rounded-lg">
          {error}
        </div>
      )}
      {success && (
        <div className="bg-green-500/10 border border-green-500/20 text-green-400 px-4 py-3 rounded-lg">
          {success}
        </div>
      )}

      {/* Suggestions based on user config */}
      {suggestions.length > 0 && (
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-2 text-blue-400">
            <Lightbulb className="h-5 w-5" />
            <span className="font-medium">Suggested Sources</span>
          </div>
          <p className="text-sm text-slate-400">
            Based on your configuration
            {basedOn.insulin && ` (${basedOn.insulin})`}
            {basedOn.pump && ` + ${basedOn.pump} pump`}
            {basedOn.cgm && ` + ${basedOn.cgm} CGM`}
            , we recommend these sources:
          </p>
          <div className="space-y-2">
            {suggestions.map((suggestion) => (
              <div key={suggestion.url} className="flex items-center justify-between bg-slate-800/50 rounded px-3 py-2">
                <div>
                  <p className="text-sm font-medium text-white">{suggestion.name}</p>
                  <p className="text-xs text-slate-500 truncate max-w-md">{suggestion.url}</p>
                </div>
                <button
                  onClick={() => handleAddSource(suggestion.url, suggestion.name, suggestion.category)}
                  disabled={adding}
                  className="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors disabled:opacity-50"
                >
                  Add
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Configured sources */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
            Configured Sources ({sources.length})
          </h2>
          <div className="flex gap-2">
            <button
              onClick={handleResearch}
              disabled={researching || sources.length === 0}
              className="flex items-center gap-2 px-3 py-2 bg-purple-600 hover:bg-purple-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
            >
              {researching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              Research Now
            </button>
            <button
              onClick={() => setShowAddForm(true)}
              className="flex items-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition-colors"
            >
              <Plus className="h-4 w-4" />
              Add Source
            </button>
          </div>
        </div>

        {sources.length === 0 && !showAddForm && (
          <div className="text-center py-12 bg-slate-800/30 rounded-lg">
            <BookOpen className="h-12 w-12 text-slate-600 mx-auto mb-3" />
            <p className="text-slate-400">No research sources configured</p>
            <p className="text-sm text-slate-500 mt-1">
              Add sources above or use the suggested sources based on your devices
            </p>
          </div>
        )}

        {sources.map((source) => (
          <div key={source.id} className="bg-slate-800/50 border border-slate-700 rounded-lg p-4">
            <div className="flex items-start justify-between">
              <div className="flex-1 min-w-0">
                <p className="font-medium text-white">{source.name}</p>
                <p className="text-sm text-slate-400 truncate">{source.url}</p>
                <div className="flex gap-3 mt-2 text-xs text-slate-500">
                  {source.category && <span className="bg-slate-700 px-2 py-0.5 rounded">{source.category}</span>}
                  {source.last_researched_at ? (
                    <span>Last researched: {new Date(source.last_researched_at).toLocaleDateString()}</span>
                  ) : (
                    <span>Not yet researched</span>
                  )}
                </div>
              </div>
              <button
                onClick={() => handleDelete(source.id, source.name)}
                className="text-slate-500 hover:text-red-400 transition-colors p-1"
                title="Remove source"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Add source form */}
      {showAddForm && (
        <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-4 space-y-3">
          <h3 className="font-medium text-white">Add Research Source</h3>
          <div>
            <label className="block text-sm text-slate-400 mb-1">URL (HTTPS required)</label>
            <input
              type="url"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="https://www.example.com/documentation"
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Name</label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g., Humalog Prescribing Information"
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-400 mb-1">Category (optional)</label>
            <select
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white text-sm"
            >
              <option value="">Select category...</option>
              <option value="insulin">Insulin / Medication</option>
              <option value="pump">Insulin Pump</option>
              <option value="cgm">CGM</option>
              <option value="guidelines">Clinical Guidelines</option>
              <option value="other">Other</option>
            </select>
          </div>
          <div className="flex gap-2 pt-2">
            <button
              onClick={() => handleAddSource(newUrl, newName, newCategory || undefined)}
              disabled={adding || !newUrl || !newName}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors disabled:opacity-50"
            >
              {adding ? "Adding..." : "Add Source"}
            </button>
            <button
              onClick={() => { setShowAddForm(false); setNewUrl(""); setNewName(""); setNewCategory(""); }}
              className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
