"use client"

import * as React from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Copy, Check, ChevronDown, ExternalLink } from "lucide-react"

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import { highlightCode } from "@/lib/code-highlight"
import { openNativeFilePreviewWindow } from "@/components/panels/files-panel"
import type { SessionView } from "@/features/dashboard/types"
import { useTranslations } from "next-intl"

export function MarkdownText({
  text,
  token,
  session,
  inverted,
}: {
  text: string
  token?: string
  session?: SessionView
  inverted?: boolean
}) {
  // The agent sometimes pastes a raw tool-execution transcript (e.g.
  // `Tool results: [Read] 1\tpackage ...`, cat -n output) straight into its
  // prose. react-markdown collapses the newlines inside such a paragraph into
  // spaces, so line numbers and code mash into one unreadable run-on and drag
  // the surrounding summary along with it. Split those transcript runs out of
  // the markdown stream and render each in a collapsed, line-preserving block;
  // the remaining prose renders as clean, neatly-broken markdown. Mirrors the
  // Android client's ToolTranscriptBlock. The trigger is deliberately narrow so
  // ordinary replies never match.
  const segments = React.useMemo(() => splitTranscriptSegments(text), [text])

  return (
    <div
      className={cn(
        "space-y-3 text-sm leading-relaxed [&_a]:underline [&_blockquote]:border-l [&_blockquote]:pl-3 [&_code]:code-mono [&_code]:text-[0.92em] [&_li]:ml-5 [&_ol]:list-decimal [&_pre]:m-0 [&_ul]:list-disc",
        inverted
          ? "[&_pre]:border-primary-foreground/15"
          : "[&_pre]:border-border",
      )}
    >
      {segments.map((segment, index) =>
        segment.type === "transcript" ? (
          <ToolTranscriptBlock key={index} text={segment.text} />
        ) : (
          <MarkdownSegment key={index} text={segment.text} token={token} session={session} />
        ),
      )}
    </div>
  )
}

function MarkdownSegment({
  text,
  token,
  session,
}: {
  text: string
  token?: string
  session?: SessionView
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        code({ className, children, ...props }) {
          const match = /language-(\w+)/.exec(className ?? "")
          const code = String(children).replace(/\n$/, "")
          if (!match) {
            const previewPath = typeof children === "string" ? parseInlineFileRef(children) : null
            if (previewPath && token && session) {
              return (
                <span
                  role="button"
                  tabIndex={0}
                  className="code-mono inline-flex max-w-full items-baseline gap-0.5 rounded-none bg-transparent p-0 align-baseline text-[0.92em] text-inherit underline underline-offset-2 hover:text-foreground"
                  onClick={() => openSessionFilePreview(token, session, previewPath)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") openSessionFilePreview(token, session, previewPath)
                  }}
                >
                  <span className="min-w-0 truncate">{children}</span>
                  <ExternalLink className="relative -top-0.5 size-3 shrink-0" />
                </span>
              )
            }
            return (
              <code
                className={cn(
                  className,
                  "rounded-md bg-secondary px-1.5 py-0.5 text-secondary-foreground",
                )}
                {...props}
              >
                {children}
              </code>
            )
          }
          return <MarkdownCodeBlock code={code} language={match[1] ?? "text"} />
        },
        a({ href, children, node: _node, ...props }) {
          const childText = textFromReactChildren(children)
          const path = href && isMarkdownFilePath(href)
            ? stripLineSuffix(href)
            : parseInlineFileRef(childText)
          if (!path || !token || !session) {
            return (
              <a href={href} target="_blank" rel="noreferrer" {...props}>
                {children}
              </a>
            )
          }
          return (
            <span
              role="button"
              tabIndex={0}
              className="inline-flex max-w-full items-baseline gap-0.5 align-baseline text-left underline underline-offset-2 hover:text-foreground"
              onClick={() => openSessionFilePreview(token, session, path)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") openSessionFilePreview(token, session, path)
              }}
            >
              <span className="min-w-0 truncate">{children}</span>
              <ExternalLink className="relative -top-0.5 size-3 shrink-0" />
            </span>
          )
        },
        table({ children, ...props }) {
          return (
            <ScrollArea contentWide className="my-3 min-w-0 max-w-full rounded-xl border border-border">
              <table className="w-full min-w-max border-collapse text-sm" {...props}>
                {children}
              </table>
              <ScrollBar orientation="horizontal" />
            </ScrollArea>
          )
        },
        thead({ children, ...props }) {
          return (
            <thead className="border-b border-border bg-muted/40" {...props}>
              {children}
            </thead>
          )
        },
        tbody({ children, ...props }) {
          return <tbody className="divide-y divide-border" {...props}>{children}</tbody>
        },
        tr({ children, ...props }) {
          return (
            <tr className="transition-colors hover:bg-muted/25" {...props}>
              {children}
            </tr>
          )
        },
        th({ children, ...props }) {
          return (
            <th className="border-r border-border px-3 py-2 text-left font-medium text-foreground last:border-r-0" {...props}>
              {children}
            </th>
          )
        },
        td({ children, ...props }) {
          return (
            <td className="border-r border-border px-3 py-2 align-top text-foreground/90 last:border-r-0" {...props}>
              {children}
            </td>
          )
        },
      }}
    >
      {text}
    </ReactMarkdown>
  )
}

type TranscriptSegment = { type: "markdown" | "transcript"; text: string }

// Tool-execution transcripts the agent occasionally pastes into its prose. The
// trigger is deliberately narrow so ordinary replies never match: either the
// literal "Tool results:" header, or a line that opens with a known tool tag
// like [Read] / [Bash] / [Edit] followed by cat -n style numbered output.
const TOOL_TAG_LINE = /^\s*\[(Read|Bash|Edit|Write|Grep|Glob|LS|Task|WebFetch|WebSearch|MultiEdit|NotebookEdit)\]/
const FENCE_BOUNDARY = /^\s*(```|~~~)/

function lineLooksLikeTranscript(line: string): boolean {
  return line.includes("Tool results:") || TOOL_TAG_LINE.test(line)
}

// Walk the raw text line by line and carve out runs of pasted tool transcript
// from the surrounding markdown. A transcript run, once started, greedily
// absorbs following lines (including the blank lines inside a single dump) until
// the text clearly returns to prose — a blank line followed by a non-transcript,
// non-indented line. Lines inside a fenced code block are never eligible so we
// don't hijack legitimately fenced output.
function splitTranscriptSegments(text: string): TranscriptSegment[] {
  if (!text) return [{ type: "markdown", text }]
  const lines = text.split("\n")
  const segments: TranscriptSegment[] = []
  let buffer: string[] = []
  let mode: "markdown" | "transcript" = "markdown"
  let inFence = false

  const flush = () => {
    if (buffer.length === 0) return
    const joined = buffer.join("\n")
    // Drop a segment that is only whitespace back into the previous one so we
    // never emit an empty transcript block.
    if (mode === "transcript" && joined.trim() === "") {
      segments.push({ type: "markdown", text: joined })
    } else {
      segments.push({ type: mode, text: joined })
    }
    buffer = []
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i] ?? ""
    if (FENCE_BOUNDARY.test(line)) inFence = !inFence

    if (mode === "markdown") {
      if (!inFence && lineLooksLikeTranscript(line)) {
        flush()
        mode = "transcript"
      }
      buffer.push(line)
      continue
    }

    // mode === "transcript": keep absorbing until prose clearly resumes.
    const isBlank = line.trim() === ""
    const nextLine = lines[i + 1]
    const nextResumesProse =
      nextLine !== undefined &&
      nextLine.trim() !== "" &&
      !/^\s/.test(nextLine) &&
      !lineLooksLikeTranscript(nextLine)
    if (isBlank && nextResumesProse) {
      flush()
      mode = "markdown"
      buffer.push(line)
      continue
    }
    buffer.push(line)
  }
  flush()

  return segments.length > 0 ? segments : [{ type: "markdown", text }]
}

function ToolTranscriptBlock({ text }: { text: string }) {
  const tSession = useTranslations("dashboard.session")
  const trimmed = text.replace(/\s+$/, "")
  const lineCount = trimmed === "" ? 0 : trimmed.split("\n").length
  return (
    <Collapsible className="my-3 min-w-0 max-w-full overflow-hidden">
      <div className="min-w-0 max-w-full space-y-2 overflow-hidden">
        <CollapsibleTrigger asChild>
          <button className="group flex h-8 w-full min-w-0 items-center gap-2 rounded-md bg-muted/25 px-2 text-left text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground">
            <ChevronDown className="size-3.5 shrink-0 -rotate-90 transition-transform group-data-[state=open]:rotate-0" />
            <span className="min-w-0 flex-1 truncate text-xs font-medium">{tSession("toolResults")}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{tSession("toolResultsLines", { count: lineCount })}</span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent className="min-w-0 max-w-full overflow-hidden">
          <ScrollArea contentWide className="max-h-96 min-w-0 max-w-full overflow-hidden rounded-xl border border-border bg-background">
            <pre className="code-mono w-max min-w-full p-3 text-xs leading-relaxed whitespace-pre">
              <code>{trimmed}</code>
            </pre>
            <ScrollBar orientation="horizontal" />
          </ScrollArea>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

function MarkdownCodeBlock({ code, language }: { code: string; language: string }) {
  const tSession = useTranslations("dashboard.session")
  const [copied, setCopied] = React.useState(false)
  return (
    <div className="my-3 min-w-0 max-w-full overflow-hidden rounded-xl border border-border bg-background">
      <div className="flex h-9 items-center justify-between border-b bg-muted/25 px-3">
        <span className="code-mono text-xs text-muted-foreground">{language || "text"}</span>
        <button
          type="button"
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          onClick={() => {
            navigator.clipboard.writeText(code).catch(() => undefined)
            setCopied(true)
            setTimeout(() => setCopied(false), 1200)
          }}
          aria-label={tSession("copyCode")}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
        </button>
      </div>
      <ScrollArea contentWide className="max-h-96 min-w-0 max-w-full overflow-hidden">
        <pre className="code-mono w-max min-w-full p-3 text-xs leading-relaxed">
          <code>{highlightCode(code, language)}</code>
        </pre>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </div>
  )
}

function stripLineSuffix(path: string) {
  return path.replace(/:\d+(?::\d+)?$/, "")
}

function parseInlineFileRef(text: string): string | null {
  if (!text || text.includes(" ") || text.includes("://")) return null
  if (!text.includes("/")) return null
  if (!/\.[a-zA-Z0-9]+(?::\d+(?::\d+)?)?$/.test(text)) return null
  return stripLineSuffix(text)
}

function textFromReactChildren(children: React.ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children)
  if (Array.isArray(children)) return children.map(textFromReactChildren).join("")
  return ""
}

function isMarkdownFilePath(href: string): boolean {
  if (!href) return false
  if (
    href.startsWith("http://") ||
    href.startsWith("https://") ||
    href.startsWith("mailto:") ||
    href.startsWith("#") ||
    href.startsWith("//")
  ) {
    return false
  }
  return true
}

export function openSessionFilePreview(token: string, session: SessionView, path: string) {
  openNativeFilePreviewWindow({
    token,
    connectorId: session.connectorId,
    root: session.cwd || ".",
    file: { name: fileNameFromPath(path), path },
  })
}

function fileNameFromPath(path: string) {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "")
  return normalized.split("/").pop() || path
}
