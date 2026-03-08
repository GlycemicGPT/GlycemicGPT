"use client";

/**
 * Story 11.2: Web-Based AI Chat Interface
 *
 * Chat interface for asking the AI questions about glucose data.
 * Messages are standalone Q&A (no persistent conversation history).
 * Shows a prompt to configure AI if no provider is set up.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { MessageSquare, Send, AlertTriangle, Settings, Loader2, Trash2 } from "lucide-react";
import Link from "next/link";
import { sendAIChat, getAIProvider } from "@/lib/api";
import { MarkdownContent } from "@/components/ui/markdown-content";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  disclaimer?: string;
}

type PageState = "loading" | "no-provider" | "ready" | "offline";

export default function AIChatPage() {
  const [pageState, setPageState] = useState<PageState>("loading");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Check if AI provider is configured on mount
  useEffect(() => {
    let cancelled = false;
    async function checkProvider() {
      try {
        await getAIProvider();
        if (!cancelled) setPageState("ready");
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : "";
        if (message.includes("No AI provider configured") || message.includes("404")) {
          setPageState("no-provider");
        } else {
          setPageState("offline");
        }
      }
    }
    checkProvider();
    return () => { cancelled = true; };
  }, []);

  const handleRetry = useCallback(async () => {
    setPageState("loading");
    try {
      await getAIProvider();
      setPageState("ready");
    } catch (err) {
      const message = err instanceof Error ? err.message : "";
      if (message.includes("No AI provider configured") || message.includes("404")) {
        setPageState("no-provider");
      } else {
        setPageState("offline");
      }
    }
  }, []);

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isSending) return;

    setError(null);

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsSending(true);

    try {
      const response = await sendAIChat(trimmed);
      const assistantMessage: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: response.response,
        timestamp: new Date(),
        disclaimer: response.disclaimer,
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to get response";
      setError(message);
    } finally {
      setIsSending(false);
      inputRef.current?.focus();
    }
  }, [input, isSending]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handleClearChat = useCallback(() => {
    setMessages([]);
    setError(null);
  }, []);

  // Loading state
  if (pageState === "loading") {
    return (
      <div className="flex flex-col h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
        <p className="mt-4 text-slate-500 dark:text-slate-400">Checking AI provider...</p>
      </div>
    );
  }

  // No AI provider configured
  if (pageState === "no-provider") {
    return (
      <div className="flex flex-col h-full items-center justify-center px-4">
        <div className="max-w-md text-center space-y-6">
          <div className="mx-auto w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
            <MessageSquare className="h-8 w-8 text-slate-400 dark:text-slate-500" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">AI Chat</h1>
          <p className="text-slate-500 dark:text-slate-400">
            To use AI Chat, you need to configure an AI provider first. Set up your
            Claude or OpenAI API key in Settings.
          </p>
          <Link
            href="/dashboard/settings/ai-provider"
            className="inline-flex items-center gap-2 px-6 py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-lg font-medium transition-colors"
          >
            <Settings className="h-5 w-5" />
            Configure AI Provider
          </Link>
        </div>
      </div>
    );
  }

  // Offline state
  if (pageState === "offline") {
    return (
      <div className="flex flex-col h-full items-center justify-center px-4">
        <div className="max-w-md text-center space-y-6">
          <div className="mx-auto w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
            <AlertTriangle className="h-8 w-8 text-yellow-500" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Unable to Connect</h1>
          <p className="text-slate-500 dark:text-slate-400">
            Cannot reach the server. Please check your connection and try again.
          </p>
          <button
            onClick={handleRetry}
            className="inline-flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  // Ready state - main chat interface
  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center">
            <MessageSquare className="h-5 w-5 text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">AI Chat</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              Ask questions about your glucose data
            </p>
          </div>
        </div>
        {messages.length > 0 && (
          <button
            onClick={handleClearChat}
            className="flex items-center gap-2 px-3 py-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
            aria-label="Clear chat history"
          >
            <Trash2 className="h-4 w-4" />
            Clear
          </button>
        )}
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6" role="log" aria-live="polite" aria-label="Chat messages">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
              <MessageSquare className="h-8 w-8 text-slate-400 dark:text-slate-500" />
            </div>
            <div>
              <p className="text-lg font-medium text-slate-900 dark:text-white">
                Start a conversation
              </p>
              <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                Ask about your glucose patterns, trends, or any diabetes-related questions.
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2 max-w-lg">
              {[
                "How am I doing today?",
                "Why do I spike after breakfast?",
                "What are my patterns this week?",
                "How is my time in range?",
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => {
                    setInput(suggestion);
                    inputRef.current?.focus();
                  }}
                  className="px-3 py-2 text-sm text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-lg border border-slate-300 dark:border-slate-700 transition-colors"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200"
              }`}
            >
              {msg.role === "assistant" ? (
                <MarkdownContent content={msg.content} />
              ) : (
                <div className="whitespace-pre-wrap text-sm leading-relaxed">
                  {msg.content}
                </div>
              )}
              {msg.disclaimer && (
                <p className="mt-2 pt-2 border-t border-slate-300 dark:border-slate-700 text-xs text-slate-500 dark:text-slate-400 flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  {msg.disclaimer}
                </p>
              )}
              <p className="text-xs mt-1 opacity-60">
                {msg.timestamp.toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
            </div>
          </div>
        ))}

        {/* Typing indicator */}
        {isSending && (
          <div className="flex justify-start" role="status" aria-label="AI is generating a response">
            <div className="bg-slate-100 dark:bg-slate-800 rounded-2xl px-4 py-3">
              <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                AI is thinking...
              </div>
            </div>
          </div>
        )}

        {/* Error message */}
        {error && (
          <div className="flex justify-center">
            <div className="bg-red-900/30 border border-red-700 rounded-lg px-4 py-3 max-w-md">
              <p className="text-sm text-red-300 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 flex-shrink-0" />
                {error}
              </p>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Disclaimer bar */}
      <div className="px-6 py-1 text-center">
        <p className="text-xs text-slate-500">
          Not medical advice. Consult your healthcare provider.
        </p>
      </div>

      {/* Input area */}
      <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-800">
        <div className="flex items-end gap-3">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your glucose data..."
            aria-label="Message input"
            disabled={isSending}
            rows={1}
            maxLength={2000}
            className="flex-1 bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl px-4 py-3 text-slate-900 dark:text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 resize-none text-sm"
            style={{ maxHeight: "120px" }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isSending}
            className="flex items-center justify-center w-12 h-12 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:cursor-not-allowed text-white rounded-xl transition-colors flex-shrink-0"
            aria-label="Send message"
          >
            {isSending ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <Send className="h-5 w-5" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
