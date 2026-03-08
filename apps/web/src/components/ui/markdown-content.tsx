"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import clsx from "clsx";
import type { Components, ExtraProps } from "react-markdown";

const REMARK_PLUGINS = [remarkGfm];

const components: Components = {
  strong: ({ children }) => (
    <strong className="font-semibold text-slate-900 dark:text-white">{children}</strong>
  ),
  ul: ({ children }) => (
    <ul className="pl-4 mb-2 space-y-1 list-disc">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="pl-4 mb-2 space-y-1 list-decimal">{children}</ol>
  ),
  li: ({ children }) => <li className="text-slate-200">{children}</li>,
  code: ({ className, children, node }: React.ComponentPropsWithoutRef<"code"> & ExtraProps) => {
    // Block code: has a language class, spans multiple lines, or is a child of <pre>
    const isBlock =
      className?.includes("language-") ||
      (node?.position && node.position.start.line !== node.position.end.line) ||
      node?.properties?.className;
    if (isBlock) {
      return (
        <code className="block bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg p-3 text-xs font-mono overflow-x-auto my-2">
          {children}
        </code>
      );
    }
    return (
      <code className="bg-slate-700 text-emerald-300 px-1.5 py-0.5 rounded text-xs font-mono">
        {children}
      </code>
    );
  },
  pre: ({ children }) => <pre className="my-2">{children}</pre>,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-slate-600 pl-3 italic text-slate-500 dark:text-slate-400">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => {
    const lower = href?.toLowerCase() ?? "";
    if (
      lower.startsWith("https://") || lower.startsWith("http://") || lower.startsWith("mailto:")
    ) {
      return (
        <a
          href={href}
          className="text-blue-400 hover:text-blue-300 underline"
          target="_blank"
          rel="noopener noreferrer"
        >
          {children}
        </a>
      );
    }
    // Blocked scheme (javascript:, data:, etc.) -- render as plain text
    return <span>{children}</span>;
  },
  // Suppress images to prevent tracking pixel / IP exfiltration from AI responses
  img: () => null,
  h1: ({ children }) => (
    <h1 className="text-lg font-bold text-slate-900 dark:text-white mt-3 mb-1">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-base font-bold text-slate-900 dark:text-white mt-3 mb-1">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-sm font-bold text-slate-900 dark:text-white mt-2 mb-1">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="text-sm font-semibold text-slate-900 dark:text-white mt-2 mb-1">{children}</h4>
  ),
  h5: ({ children }) => (
    <h5 className="text-xs font-semibold text-slate-900 dark:text-white mt-2 mb-1">{children}</h5>
  ),
  h6: ({ children }) => (
    <h6 className="text-xs font-medium text-slate-200 mt-2 mb-1">{children}</h6>
  ),
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  hr: () => <hr className="border-slate-300 dark:border-slate-700 my-3" />,
  table: ({ children }) => (
    <div className="overflow-x-auto my-2">
      <table className="min-w-full text-xs border-collapse">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-slate-300 dark:border-slate-700 px-2 py-1 text-left font-semibold text-slate-200 bg-slate-100 dark:bg-slate-800">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-slate-300 dark:border-slate-700 px-2 py-1 text-slate-600 dark:text-slate-300">
      {children}
    </td>
  ),
};

interface MarkdownContentProps {
  content: string;
  className?: string;
}

export const MarkdownContent = memo(function MarkdownContent({
  content,
  className,
}: MarkdownContentProps) {
  if (!content) {
    return null;
  }
  return (
    <div className={clsx("text-sm leading-relaxed", className)}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
});
