import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"
import { cn } from "@/lib/utils"

/**
 * MarkdownView — renderer markdown bersama untuk knowledge (FE-7).
 * DRY reuse react-markdown + rehype-highlight (stack chat FE-5) + remark-gfm
 * (tabel, task list, strikethrough, autolink). Lazy-load via dynamic import.
 */
export function MarkdownView({ content, className }: { content: string; className?: string }) {
  return (
    <div
      className={cn(
        "prose-sm break-words [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground",
        "[&_code]:font-mono [&_h1]:mb-2 [&_h1]:mt-4 [&_h1]:text-base [&_h1]:font-semibold",
        "[&_h2]:mb-2 [&_h2]:mt-4 [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:mb-1.5 [&_h3]:mt-3 [&_h3]:text-sm [&_h3]:font-semibold",
        "[&_hr]:my-4 [&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5",
        "[_p]:my-2 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-code-block [&_pre]:p-3 [&_pre]:text-xs [&_pre]:text-code-block-fg [&_pre]:border [&_pre]:border-code-block-border",
        "[_strong]:font-semibold [&_table]:my-2 [&_table]:w-full [&_table]:text-xs",
        "[_td]:border-b [&_td]:px-2 [&_td]:py-1 [&_th]:border-b [&_th]:bg-muted/50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold",
        "[_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5",
        className,
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
        {content}
      </ReactMarkdown>
    </div>
  )
}

export default MarkdownView
