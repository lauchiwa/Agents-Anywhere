"use client"

import React from "react"
import { Bell, BookOpen, Check, ChevronDown, CircleAlert, Clock, Copy, FilePenLine, RefreshCw, Sparkles, Wrench, Zap } from "lucide-react"
import dynamic from "next/dynamic"
import { useTranslations } from "next-intl"
import { toast } from "sonner"

import { copyText } from "@/lib/clipboard"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { JsonBlock, TimelineStatusBadge, ToolCard } from "@/components/session/session-tool-cards"
import { openSessionFilePreview } from "@/components/markdown-text"
import { cn } from "@/lib/utils"
import type { Approval, ApprovalResolveStatus, ApprovalSelection, SessionView, TimelineItem } from "@/features/dashboard/types"
import { firstTextOf, messageText, recordsOf, textOf } from "@/components/session/session-utils"
import { extractAttachments, stripInjectedAttachmentMentions } from "@/features/dashboard/attachments"
import { MessageAttachments } from "@/components/session/message-attachments"
import { CollapsibleUserMessage } from "@/components/session/collapsible-user-message"

const MarkdownText = dynamic(() => import("../markdown-text").then((mod) => ({ default: mod.MarkdownText })), { ssr: false })

export function TimelineEntry({
  token,
  session,
  item,
  approval,
  childItems,
  resolvingApprovalId,
  resolvingStatus,
  onResolveApproval,
  onRetryMessage,
}: {
  token: string
  session: SessionView
  item: TimelineItem
  approval?: Approval
  childItems?: TimelineItem[]
  resolvingApprovalId: string | null
  resolvingStatus: ApprovalResolveStatus | null
  onResolveApproval: (
    approvalId: string,
    status: ApprovalResolveStatus,
    selections?: ApprovalSelection[],
  ) => void
  onRetryMessage?: (item: TimelineItem) => void
}) {
  if (item.type === "turn.start" || item.type === "turn.end") return null
  if (item.type === "message") return <MessageCard token={token} session={session} item={item} onRetryMessage={onRetryMessage} />
  if (item.type === "tool") {
    // Subagent (Task) output is nested under the parent tool card. Build the
    // child nodes here and hand them to ToolCard as a slot to avoid a circular
    // import (this module already imports ToolCard).
    const childrenContent = childItems && childItems.length > 0 ? (
      <div className="mt-2 space-y-2 border-l border-border/60 pl-3">
        {childItems.map((child) => (
          <TimelineEntry
            key={child.id}
            token={token}
            session={session}
            item={child}
            resolvingApprovalId={resolvingApprovalId}
            resolvingStatus={resolvingStatus}
            onResolveApproval={onResolveApproval}
          />
        ))}
      </div>
    ) : null
    return (
      <ToolCard
        item={item}
        token={token}
        session={session}
        approval={approval}
        childrenContent={childrenContent}
        resolvingApprovalId={resolvingApprovalId}
        resolvingStatus={resolvingStatus}
        onResolveApproval={onResolveApproval}
      />
    )
  }
  if (item.type === "system") return <SystemCard item={item} />
  if (item.type === "artifact") return <ArtifactCard token={token} session={session} item={item} />
  return null
}

function MessageCard({
  token,
  session,
  item,
  onRetryMessage,
}: {
  token: string
  session: SessionView
  item: TimelineItem
  onRetryMessage?: (item: TimelineItem) => void
}) {
  const tSession = useTranslations("dashboard.session")
  const text = stripInjectedAttachmentMentions(messageText(item))
  const attachments = extractAttachments(item.content)
  const isUser = item.role === "user"
  const hasAttachments = attachments.length > 0
  const isFailed = isUser && item.status === "failed"
  const showUserStatus = isUser && (item.status === "pending" || item.status === "failed")
  const [copied, setCopied] = React.useState(false)
  const content = text ? (
    <MarkdownText text={text} token={token} session={session} />
  ) : hasAttachments ? null : (
    <JsonBlock value={item.content} />
  )
  const attachmentList = (
    <MessageAttachments
      token={token}
      sessionId={session.id}
      attachments={attachments}
      align={isUser ? "right" : "left"}
    />
  )

  return (
    <div className={cn("group/msg flex min-w-0 max-w-full overflow-hidden", isUser && "justify-end")}>
      <div className={cn("flex min-w-0 max-w-[88%] flex-col gap-2 text-sm leading-relaxed", isUser && "items-end")}>
        {isUser ? attachmentList : null}
        {content ? (
          <div
            className={cn(
              "relative min-w-0 max-w-full",
              isUser ? "rounded-2xl bg-secondary px-4 py-3 text-secondary-foreground" : "bg-transparent px-0 py-1",
            )}
          >
            {isUser ? <CollapsibleUserMessage>{content}</CollapsibleUserMessage> : content}
            {!isUser && text ? (
              <button
                type="button"
                aria-label={copied ? "Copied" : "Copy"}
                onClick={() => {
                  copyText(text)
                    .then(() => {
                      setCopied(true)
                      setTimeout(() => setCopied(false), 1200)
                    })
                    .catch((err) => toast.error(err instanceof Error ? err.message : "Copy failed"))
                }}
                className="absolute -right-7 top-0 rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground group-hover/msg:opacity-100"
              >
                {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              </button>
            ) : null}
          </div>
        ) : null}
        {!isUser ? attachmentList : null}
        {!content && !hasAttachments ? (
          <div className="min-w-0 max-w-full bg-transparent px-0 py-1">
            <JsonBlock value={item.content} />
          </div>
        ) : null}
        {showUserStatus ? (
          <div className="flex items-center gap-2">
            <TimelineStatusBadge status={item.status} />
            {isFailed && onRetryMessage ? (
              <button
                type="button"
                onClick={() => onRetryMessage(item)}
                className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <RefreshCw className="size-3" />
                {tSession("retry")}
              </button>
            ) : null}
          </div>
        ) : null}
        {isFailed && hasAttachments ? (
          <span className="text-[11px] text-muted-foreground">{tSession("retryAttachmentsHint")}</span>
        ) : null}
      </div>
    </div>
  )
}

function SystemCard({ item }: { item: TimelineItem }) {
  const kind = textOf(item.content.kind) || "system"
  if (kind === "reasoning") return <ReasoningEntry item={item} />
  if (kind === "compact") return <CompactEntry item={item} />
  if (kind === "notification") return <NotificationEntry item={item} />
  if (kind === "skill_listing") return <SkillListingEntry item={item} />
  if (kind === "deferred_tools_delta") return <DeferredToolsDeltaEntry item={item} />
  if (kind === "invoked_skills") return <InvokedSkillsEntry item={item} />
  const text = textOf(item.content.text) || textOf(item.content.message) || textOf(item.content.rawText)
  const failed = item.status === "failed" || kind === "error"
  return (
    <div className={cn("flex items-start gap-2 rounded-lg border px-3 py-2 text-sm", failed ? "border-destructive/35 bg-destructive/5 text-destructive" : "border-border bg-muted/20 text-muted-foreground")}>
      {failed ? <CircleAlert className="mt-0.5 size-4 shrink-0" /> : <Clock className="mt-0.5 size-4 shrink-0" />}
      <div className="min-w-0">
        <div className="font-medium">{kind}</div>
        <div className="wrap-break-word">{text || item.status}</div>
      </div>
    </div>
  )
}

function NotificationEntry({ item }: { item: TimelineItem }) {
  // A CLI-initiated Notification hook (include_hook_events): the agent is
  // asking for the user's attention (e.g. a permission prompt or an idle
  // nudge). Render an amber attention banner distinct from the neutral system
  // card, with the optional hook-supplied title above the message.
  const title = textOf(item.content.title)
  const message = textOf(item.content.message) || textOf(item.content.text)
  const notificationType = textOf(item.content.notificationType)
  const [copied, setCopied] = React.useState(false)
  const copy = () => {
    if (!message) return
    copyText(message)
      .then(() => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      })
      .catch((err) => toast.error(err instanceof Error ? err.message : "Copy failed"))
  }
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-500/35 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
      <Bell className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          {title ? <span className="font-medium">{title}</span> : null}
          {notificationType ? (
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs font-medium opacity-80">{notificationType}</span>
          ) : null}
        </div>
        <div className="wrap-break-word">{message || item.status}</div>
      </div>
      {message ? (
        <button
          type="button"
          onClick={copy}
          title="Copy"
          className="mt-0.5 shrink-0 opacity-50 transition-opacity hover:opacity-100"
        >
          <Copy className="size-3.5" />
          <span className="sr-only">{copied ? "Copied" : "Copy"}</span>
        </button>
      ) : null}
    </div>
  )
}

function CompactEntry({ item }: { item: TimelineItem }) {
  const tSession = useTranslations("dashboard.session")
  // Context-compaction separator: the connector emits this where the CLI
  // auto-compacted the window. Render a centered, non-expandable divider so the
  // user understands why earlier history vanished, with the before/after token
  // counts when the connector supplied them.
  const pre = typeof item.content.preTokens === "number" ? item.content.preTokens : null
  const post = typeof item.content.postTokens === "number" ? item.content.postTokens : null
  const detail =
    pre !== null && post !== null
      ? tSession("contextCompactedTokens", { pre: pre.toLocaleString(), post: post.toLocaleString() })
      : null
  return (
    <div className="flex items-center gap-3 py-1 text-xs text-muted-foreground">
      <div className="h-px flex-1 bg-border" />
      <div className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <Sparkles className="size-3.5 shrink-0" />
        <span className="font-medium">{tSession("contextCompacted")}</span>
        {detail ? <span className="text-muted-foreground/80">· {detail}</span> : null}
      </div>
      <div className="h-px flex-1 bg-border" />
    </div>
  )
}

function reasoningDurationSeconds(item: TimelineItem): number | null {
  // Thinking duration is a free client-side derivation: the connector stamps
  // createdAt when the block opens and completedAt when it converges. No
  // dedicated duration field is sent.
  if (!item.completedAt) return null
  const started = Date.parse(item.createdAt)
  const finished = Date.parse(item.completedAt)
  if (Number.isNaN(started) || Number.isNaN(finished)) return null
  const seconds = Math.round((finished - started) / 1000)
  return seconds > 0 ? seconds : null
}

function ReasoningEntry({ item }: { item: TimelineItem }) {
  const tSession = useTranslations("dashboard.session")
  const streaming = item.status === "running"
  const redacted = item.content.redacted === true
  const summaries = recordsOf(item.content.summaries)
    .map((summary) => textOf(summary.text))
    .filter((text): text is string => Boolean(text))
  const rawText = textOf(item.content.rawText) || textOf(item.content.text)
  const lines = summaries.length > 0 ? summaries : rawText ? [rawText] : []
  const duration = streaming ? null : reasoningDurationSeconds(item)
  const label = streaming
    ? tSession("reasoningThinking")
    : duration !== null
      ? tSession("reasoningDuration", { seconds: duration })
      : tSession("reasoning")
  return (
    <Collapsible className="min-w-0 max-w-full overflow-hidden">
      <div className="min-w-0 max-w-full space-y-2 overflow-hidden">
        <CollapsibleTrigger asChild>
          <button className="group inline-flex h-7 max-w-full items-center gap-1.5 rounded-full bg-secondary px-2.5 text-left text-xs font-medium text-secondary-foreground transition-colors hover:bg-secondary/80">
            <ChevronDown className="size-3.5 shrink-0 -rotate-90 transition-transform group-data-[state=open]:rotate-0" />
            <Sparkles className={cn("size-3.5 shrink-0", streaming && "animate-pulse")} />
            <span className="truncate">{label}</span>
          </button>
        </CollapsibleTrigger>
        {redacted ? (
          <CollapsibleContent className="min-w-0 max-w-full overflow-hidden">
            <div className="pl-1 text-sm italic leading-relaxed text-muted-foreground">
              {tSession("reasoningRedacted")}
            </div>
          </CollapsibleContent>
        ) : lines.length > 0 ? (
          <CollapsibleContent className="min-w-0 max-w-full overflow-hidden">
            <div className="space-y-2 pl-1 text-sm leading-relaxed text-muted-foreground">
              {lines.map((line, index) => (
                <MarkdownText key={index} text={line} />
              ))}
            </div>
          </CollapsibleContent>
        ) : null}
      </div>
    </Collapsible>
  )
}

function ArtifactCard({ token, session, item }: { token: string; session: SessionView; item: TimelineItem }) {
  const kind = textOf(item.content.kind) || "artifact"
  if (kind === "diff") return null
  const path = firstTextOf(item.content.path, item.content.filePath, item.content.file, item.content.uri)
  const title = path ?? kind
  return (
    <Collapsible className="min-w-0 max-w-full overflow-hidden">
      <div className="min-w-0 max-w-full space-y-2 overflow-hidden">
        <CollapsibleTrigger asChild>
          <button className="group flex h-8 w-full min-w-0 items-center gap-2 rounded-md px-1 text-left text-muted-foreground transition-colors hover:bg-muted/35 hover:text-foreground">
            <ChevronDown className="size-3.5 shrink-0 -rotate-90 transition-transform group-data-[state=open]:rotate-0" />
            <FilePenLine className="size-4 shrink-0" />
            <span
              className={cn(
                "code-mono min-w-0 flex-1 truncate text-sm",
                path && "underline-offset-2 group-hover:underline",
              )}
              onClick={(event) => {
                if (!path) return
                event.preventDefault()
                event.stopPropagation()
                openSessionFilePreview(token, session, path)
              }}
            >
              {title}
            </span>
            <TimelineStatusBadge status={item.status} />
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent className="min-w-0 max-w-full overflow-hidden">
          <JsonBlock value={item.content} />
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

type SkillEntry = { name?: unknown; description?: unknown }

function SkillListingEntry({ item }: { item: TimelineItem }) {
  const skills = recordsOf(item.content.skills) as SkillEntry[]
  if (skills.length === 0) return null
  return (
    <Collapsible className="min-w-0 max-w-full overflow-hidden">
      <div className="min-w-0 max-w-full space-y-1 overflow-hidden">
        <CollapsibleTrigger asChild>
          <button className="group inline-flex h-7 max-w-full items-center gap-1.5 rounded-full bg-secondary px-2.5 text-left text-xs font-medium text-secondary-foreground transition-colors hover:bg-secondary/80">
            <ChevronDown className="size-3.5 shrink-0 -rotate-90 transition-transform group-data-[state=open]:rotate-0" />
            <BookOpen className="size-3.5 shrink-0 opacity-70" />
            <span className="truncate">{skills.length} skills available</span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent className="min-w-0 max-w-full overflow-hidden">
          <div className="space-y-0.5 pl-1 text-xs text-muted-foreground">
            {skills.map((skill, i) => (
              <div key={textOf(skill.name) ?? i} className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-3">
                <span className="code-mono truncate font-medium text-foreground">{textOf(skill.name)}</span>
                <span className="truncate">{textOf(skill.description)}</span>
              </div>
            ))}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

function DeferredToolsDeltaEntry({ item }: { item: TimelineItem }) {
  const added = Array.isArray(item.content.addedNames) ? (item.content.addedNames as unknown[]).filter(Boolean) : []
  const removed = Array.isArray(item.content.removedNames) ? (item.content.removedNames as unknown[]).filter(Boolean) : []
  if (added.length === 0 && removed.length === 0) return null
  const parts: string[] = []
  if (added.length > 0) parts.push(`+${added.length} deferred tools`)
  if (removed.length > 0) parts.push(`-${removed.length} tools`)
  return (
    <div className="inline-flex h-6 items-center gap-1.5 rounded-full bg-secondary px-2.5 text-xs font-medium text-secondary-foreground">
      <Wrench className="size-3 shrink-0 opacity-70" />
      <span>{parts.join(", ")}</span>
    </div>
  )
}

function InvokedSkillsEntry({ item }: { item: TimelineItem }) {
  const skills = recordsOf(item.content.skills) as SkillEntry[]
  if (skills.length === 0) return null
  const names = skills.map((s) => textOf(s.name)).filter(Boolean).join(", ")
  return (
    <div className="inline-flex h-6 items-center gap-1.5 rounded-full bg-secondary px-2.5 text-xs font-medium text-secondary-foreground">
      <Zap className="size-3 shrink-0 opacity-70" />
      <span className="truncate">Skills: {names}</span>
    </div>
  )
}
