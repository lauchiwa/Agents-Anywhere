"use client"

import * as React from "react"
import { Archive, ChevronDown, ChevronUp, Download, FolderOpen, GitFork, Loader2, MoreHorizontal, PanelLeft, Pin, PinOff, SquareTerminal, Tag, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { Input } from "@/components/ui/input"
import { McpServersEditor } from "@/components/mcp-servers-editor"
import { useSidebar } from "@/components/ui/sidebar"
import { useDashboardSidebarControls } from "@/components/demo"
import { useWorkspace, type PanelId } from "@/components/workspace-context"
import type { SessionMemorySnapshot } from "@/components/session-detail"
import { cn } from "@/lib/utils"
import { useTranslations } from "next-intl"
import type { SessionView as SessionViewModel } from "@/lib/demo-api"
import { useAuth } from "@/components/auth/auth-context"
import { dashboardApi } from "@/features/dashboard/api"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

type PanelIcon = React.ComponentType<React.SVGProps<SVGSVGElement>>

const PANEL_META: Record<PanelId, { titleKey: "panelFiles" | "panelShell"; icon: PanelIcon }> = {
  files: { titleKey: "panelFiles", icon: FolderOpen },
  terminal: { titleKey: "panelShell", icon: SquareTerminal },
}

const HEADER_BLUR_LAYERS = buildBlurGradientLayers({
  height: 56,
  layerCount: 9,
  maxBlur: 12,
  minBlur: 0,
  overlap: 8,
  gamma: 1.85,
})

type BlurLayerStyle = React.CSSProperties & {
  WebkitBackdropFilter?: string
  WebkitMaskImage?: string
}

type SessionViewHeaderProps = {
  session: SessionViewModel
  connectorName?: string | null
  memorySnapshot: SessionMemorySnapshot | null
  onExportMemoryTimeline?: () => void
  onExportRemoteTimeline?: () => void
  exporting?: boolean
}

export function SessionViewHeader({
  session,
  connectorName,
  memorySnapshot,
  onExportMemoryTimeline,
  onExportRemoteTimeline,
  exporting,
}: SessionViewHeaderProps) {
  const { isMobile, toggleSidebar } = useSidebar()
  const { renameSession, forkSession, deleteSession, tagSession, togglePinSession, toggleArchiveSession } = useWorkspace()
  const sidebarControls = useDashboardSidebarControls()
  const tSession = useTranslations("dashboard.session")
  const tActions = useTranslations("dashboard.actions")
  const tCommon = useTranslations("common")
  const [editingTitle, setEditingTitle] = React.useState(false)
  const [titleDraft, setTitleDraft] = React.useState(session.title ?? "")
  const [renaming, setRenaming] = React.useState(false)
  const [forking, setForking] = React.useState(false)
  const [deleteOpen, setDeleteOpen] = React.useState(false)
  const [deleting, setDeleting] = React.useState(false)
  const [tagOpen, setTagOpen] = React.useState(false)
  const [tagDraft, setTagDraft] = React.useState("")
  const [tagging, setTagging] = React.useState(false)

  React.useEffect(() => {
    if (!editingTitle) setTitleDraft(session.title ?? "")
  }, [editingTitle, session.title])

  const toggleDashboardSidebar = React.useCallback(() => {
    if (isMobile) {
      toggleSidebar()
      return
    }
    sidebarControls?.toggleSidebar()
  }, [isMobile, sidebarControls, toggleSidebar])

  const cancelRename = React.useCallback(() => {
    setTitleDraft(session.title ?? "")
    setEditingTitle(false)
  }, [session.title])

  const submitRename = React.useCallback(async () => {
    const nextTitle = titleDraft.trim()
    if (!nextTitle) {
      cancelRename()
      return
    }
    if (renaming) return
    if (nextTitle === session.title) {
      setEditingTitle(false)
      return
    }
    setRenaming(true)
    try {
      const ok = await renameSession(session.id, nextTitle)
      if (ok) setEditingTitle(false)
      else toast.error(tSession("renameFailed"))
    } finally {
      setRenaming(false)
    }
  }, [cancelRename, renameSession, renaming, session.id, session.title, tSession, titleDraft])

  return (
    <>
      <header className="pointer-events-none absolute inset-x-0 top-0 z-10 h-14 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-background/80 to-background/0" />
        {HEADER_BLUR_LAYERS.map((layer) => (
          <div key={layer.key} className={layer.className} style={layer.style} />
        ))}
        <div className="pointer-events-auto relative flex h-14 items-center gap-2 px-2">
          <Button
            variant="ghost"
            size="icon-sm"
            type="button"
            aria-label={sidebarControls?.open === false ? tActions("expand") : tActions("collapse")}
            onClick={toggleDashboardSidebar}
            className="shrink-0 text-muted-foreground hover:text-foreground"
          >
            <PanelLeft className="size-4" />
          </Button>
          {editingTitle ? (
            <Input
              autoFocus
              value={titleDraft}
              onChange={(event) => setTitleDraft(event.currentTarget.value)}
              onBlur={cancelRename}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) return
                if (event.key === "Enter") {
                  event.preventDefault()
                  void submitRename()
                }
                if (event.key === "Escape") {
                  event.preventDefault()
                  cancelRename()
                }
              }}
              disabled={renaming}
              aria-label={tSession("renameTitle")}
              className="h-8 min-w-0 max-w-[min(28rem,40vw)] flex-1 rounded-xl text-sm"
            />
          ) : (
            <button
              type="button"
              className="min-w-0 truncate rounded-md px-1 text-left text-sm font-medium hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              title={tSession("renameTitle")}
              onClick={() => {
                setTitleDraft(session.title ?? "")
                setEditingTitle(true)
              }}
            >
              {session.title}
            </button>
          )}
          <SessionMetaBadge
            session={session}
            connectorName={connectorName}
            memorySnapshot={memorySnapshot}
            onExportMemoryTimeline={onExportMemoryTimeline}
            onExportRemoteTimeline={onExportRemoteTimeline}
            exporting={exporting}
          />
          <ContextUsageBadge session={session} />
          <RateLimitBadge session={session} />
          <PlanModeBadge session={session} />
          <div className="ml-auto flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" type="button" aria-label="More actions" className="shrink-0 text-muted-foreground hover:text-foreground">
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-44">
                <DropdownMenuItem
                  disabled={forking}
                  onSelect={() => {
                    setForking(true)
                    forkSession(session.id).catch((err) => {
                      toast.error(err instanceof Error ? err.message : tActions("forkFailed"))
                    }).finally(() => setForking(false))
                  }}
                >
                  <GitFork className="size-4" />
                  {forking ? tActions("forking") : tActions("fork")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => togglePinSession(session.id)}>
                  {session.pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />}
                  {session.pinned ? tActions("unpin") : tActions("pin")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => toggleArchiveSession(session.id)}>
                  <Archive className="size-4" />
                  {session.archived ? tActions("unarchive") : tActions("archive")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => { setTagDraft(session.tag ?? ""); setTagOpen(true) }}>
                  <Tag className="size-4" />
                  {tActions("setTag")}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onSelect={() => setDeleteOpen(true)}
                >
                  <Trash2 className="size-4" />
                  {tActions("delete")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <TogglePanelButton id="files" icon={PANEL_META.files.icon} />
            <TogglePanelButton id="terminal" icon={PANEL_META.terminal.icon} />
          </div>
        </div>
      </header>

      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{tActions("deleteConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>
              {tActions("deleteConfirmDesc", { title: session.title ?? session.id })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>{tCommon("cancel")}</AlertDialogCancel>
            <AlertDialogAction
              disabled={deleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={async (e) => {
                e.preventDefault()
                setDeleting(true)
                try {
                  await deleteSession(session.id)
                  setDeleteOpen(false)
                } catch (err) {
                  toast.error(err instanceof Error ? err.message : tActions("deleteFailed"))
                } finally {
                  setDeleting(false)
                }
              }}
            >
              {deleting ? <Loader2 className="size-4 animate-spin" /> : tActions("delete")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <Dialog open={tagOpen} onOpenChange={(open) => { if (!open) { setTagOpen(false); setTagDraft("") } }}>
        <DialogContent className="sm:max-w-sm">
          <form
            className="space-y-4"
            onSubmit={async (e) => {
              e.preventDefault()
              if (tagging) return
              setTagging(true)
              try {
                await tagSession(session.id, tagDraft.trim() || null)
                setTagOpen(false)
              } catch (err) {
                toast.error(err instanceof Error ? err.message : tActions("tagFailed"))
              } finally {
                setTagging(false)
              }
            }}
          >
            <DialogHeader>
              <DialogTitle>{tActions("setTag")}</DialogTitle>
            </DialogHeader>
            <Input
              autoFocus
              value={tagDraft}
              onChange={(e) => setTagDraft(e.target.value)}
              placeholder={tActions("tagPlaceholder")}
              disabled={tagging}
            />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setTagOpen(false)} disabled={tagging}>
                {tCommon("cancel")}
              </Button>
              <Button type="submit" disabled={tagging}>
                {tagging ? <Loader2 className="size-4 animate-spin" /> : tCommon("save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

function buildBlurGradientLayers({
  height,
  layerCount,
  maxBlur,
  minBlur,
  overlap,
  gamma,
}: {
  height: number
  layerCount: number
  maxBlur: number
  minBlur: number
  overlap: number
  gamma: number
}) {
  const step = height / layerCount
  return Array.from({ length: layerCount }, (_, index) => {
    const start = Math.max(0, Math.round(index * step - overlap * 0.5))
    const end = Math.min(height, Math.round((index + 1) * step + overlap))
    const progress = index / Math.max(1, layerCount - 1)
    const blur = minBlur + (maxBlur - minBlur) * Math.pow(1 - progress, gamma)
    const fadeIn = index === 0 ? 0 : 26
    const fadeOut = index === layerCount - 1 ? 72 : 76
    const mask =
      index === 0
        ? `linear-gradient(to bottom, black 0%, black ${fadeOut}%, transparent 100%)`
        : `linear-gradient(to bottom, transparent 0%, black ${fadeIn}%, black ${fadeOut}%, transparent 100%)`

    return {
      key: `${index}-${start}-${end}-${blur.toFixed(2)}`,
      className: "absolute inset-x-0",
      style: {
        top: `${start}px`,
        height: `${Math.max(1, end - start)}px`,
        backdropFilter: `blur(${blur.toFixed(2)}px)`,
        WebkitBackdropFilter: `blur(${blur.toFixed(2)}px)`,
        maskImage: mask,
        WebkitMaskImage: mask,
      } satisfies BlurLayerStyle,
    }
  })
}

function SessionMetaBadge({
  session,
  connectorName,
  memorySnapshot,
  onExportMemoryTimeline,
  onExportRemoteTimeline,
  exporting,
}: {
  session: SessionViewModel
  connectorName?: string | null
  memorySnapshot: SessionMemorySnapshot | null
  onExportMemoryTimeline?: () => void
  onExportRemoteTimeline?: () => void
  exporting?: boolean
}) {
  const t = useTranslations("dashboard.session")
  const tMcp = useTranslations("dashboard.mcp")
  const [mcpOpen, setMcpOpen] = React.useState(false)
  const label = `${connectorName ?? session.connectorId}/${session.runtime}`
  const timelineSummary = memorySnapshot
    ? t("timelineSummary", { count: memorySnapshot.items.length, seq: memorySnapshot.nextSeq })
    : t("memoryLoading")
  const approvalsSummary = memorySnapshot
    ? t("approvalsPending", { count: memorySnapshot.pendingApprovalCount })
    : t("memoryLoading")
  const rows = [
    [t("device"), connectorName ?? session.connectorId],
    [t("runtime"), session.runtime],
    [t("status"), `${memorySnapshot?.session.status ?? session.status} · ${session.connectorStatus}`],
    [t("workspace"), memorySnapshot?.session.cwd ?? session.cwd ?? t("none")],
    [t("sessionId"), session.id],
    [t("externalId"), memorySnapshot?.session.externalSessionId ?? t("none")],
    [t("timeline"), timelineSummary],
    [t("approvals"), approvalsSummary],
  ] as const

  return (
    <HoverCard openDelay={120} closeDelay={80}>
      <HoverCardTrigger asChild>
        <Badge variant="secondary" className="shrink-0 cursor-default gap-1.5 font-normal">
          <span
            className={cn(
              "size-1.5 rounded-full",
              session.connectorStatus === "online" ? "bg-emerald-500" : "bg-muted-foreground/40",
            )}
          />
          {label}
        </Badge>
      </HoverCardTrigger>
      <HoverCardContent align="end" sideOffset={10} className="w-[420px] rounded-xl p-4">
        <div className="space-y-4">
          <h2 className="text-sm font-semibold">{t("overview")}</h2>
          <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            {rows.map(([name, value]) => (
              <React.Fragment key={name}>
                <div className="text-muted-foreground">{name}</div>
                <div className="min-w-0 truncate font-medium text-popover-foreground">{value}</div>
              </React.Fragment>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              className="font-normal"
              onClick={onExportMemoryTimeline}
              disabled={!memorySnapshot}
            >
              <Download className="size-3.5" />
              {t("exportMemoryTimelineJson")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="font-normal"
              onClick={onExportRemoteTimeline}
              disabled={exporting}
            >
              {exporting ? <Loader2 className="size-3.5 animate-spin" /> : <Download className="size-3.5" />}
              {exporting ? t("exportingTimeline") : t("exportRemoteTimelineJson")}
            </Button>
          </div>
          <div>
            <button
              type="button"
              className="flex w-full items-center justify-between py-1 text-xs font-semibold uppercase tracking-widest text-muted-foreground hover:text-foreground"
              onClick={() => setMcpOpen((v) => !v)}
            >
              {tMcp("title")}
              {mcpOpen ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
            </button>
            {mcpOpen && (
              <div className="pt-2">
                <McpServersEditor scope="session" scopeId={session.id} />
              </div>
            )}
          </div>
          <SlashCommandsSection sessionId={session.id} />
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}

type ContextUsageGauge = {
  totalTokens?: number
  maxTokens?: number
  percentage?: number
  autoCompactEnabled?: boolean
  autoCompactThreshold?: number
}

function numberOf(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

// Session-level context-window gauge, fed by the connector's get_context_usage()
// snapshot (CLI /context data) carried on session.updated. Shows percent used and
// warns when the session is close to auto-compact, so a long session's impending
// compaction is visible instead of a surprise.
function ContextUsageBadge({ session }: { session: SessionViewModel }) {
  const t = useTranslations("dashboard.session")
  const usage = session.contextUsage as ContextUsageGauge | null | undefined
  if (!usage) return null
  const total = numberOf(usage.totalTokens)
  const max = numberOf(usage.maxTokens)
  const rawPercentage = numberOf(usage.percentage)
  const percentage = rawPercentage != null
    ? rawPercentage
    : total != null && max
      ? (total / max) * 100
      : null
  if (percentage == null) return null
  const rounded = Math.round(percentage)
  // "Near auto-compact" once we cross the threshold (or 80% as a fallback when
  // the connector didn't report one). autoCompactEnabled must be on to warn.
  const thresholdPct = usage.autoCompactThreshold && max
    ? (usage.autoCompactThreshold / max) * 100
    : 80
  const nearCompact = usage.autoCompactEnabled === true && percentage >= thresholdPct

  return (
    <HoverCard openDelay={120} closeDelay={80}>
      <HoverCardTrigger asChild>
        <Badge
          variant={nearCompact ? "destructive" : "secondary"}
          className="shrink-0 cursor-default font-normal tabular-nums"
        >
          {t("contextUsage", { percentage: rounded })}
        </Badge>
      </HoverCardTrigger>
      <HoverCardContent align="end" sideOffset={10} className="w-56 rounded-xl p-3 text-sm">
        <div className="space-y-1">
          {total != null && max ? (
            <div className="text-muted-foreground">
              {t("contextUsageTokens", { used: total.toLocaleString(), max: max.toLocaleString() })}
            </div>
          ) : null}
          {nearCompact ? (
            <div className="font-medium text-destructive">{t("contextNearCompact")}</div>
          ) : null}
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}

type RateLimitSnapshot = {
  status?: string
  type?: string
  resetsAt?: number
  utilization?: number
  overageStatus?: string
  overageResetsAt?: number
}

function formatRateLimitReset(resetsAt: number | null): string | null {
  // resetsAt is a Unix timestamp (seconds). Render it as a short local time so
  // the user knows when the throttle lifts; fall back to null when absent.
  if (resetsAt == null) return null
  const ms = resetsAt > 1e12 ? resetsAt : resetsAt * 1000
  const date = new Date(ms)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
}

// Session-level rate-limit indicator, fed by the connector's RateLimitEvent
// snapshot carried on session.updated. Shows a warning when quota is nearly
// exhausted and a distinct "rate limited" state when throttled. Hidden once the
// throttle lifts (status back to "allowed").
function RateLimitBadge({ session }: { session: SessionViewModel }) {
  const t = useTranslations("dashboard.session")
  const rate = session.rateLimit as RateLimitSnapshot | null | undefined
  if (!rate) return null
  const status = rate.status
  // "allowed" is the steady state — nothing to surface. Only warn / block.
  if (status !== "allowed_warning" && status !== "rejected") return null
  const rejected = status === "rejected"
  const resets = formatRateLimitReset(numberOf(rate.resetsAt))
  const utilization = numberOf(rate.utilization)
  const utilizationPct = utilization != null ? Math.round(utilization * 100) : null

  return (
    <HoverCard openDelay={120} closeDelay={80}>
      <HoverCardTrigger asChild>
        <Badge
          variant={rejected ? "destructive" : "secondary"}
          className="shrink-0 cursor-default font-normal tabular-nums"
        >
          {rejected ? t("rateLimited") : t("rateLimitWarning")}
        </Badge>
      </HoverCardTrigger>
      <HoverCardContent align="end" sideOffset={10} className="w-56 rounded-xl p-3 text-sm">
        <div className="space-y-1">
          {utilizationPct != null ? (
            <div className="text-muted-foreground">{t("rateLimitUtilization", { percentage: utilizationPct })}</div>
          ) : null}
          {resets ? (
            <div className={rejected ? "font-medium text-destructive" : "text-muted-foreground"}>
              {t("rateLimitResets", { time: resets })}
            </div>
          ) : null}
        </div>
      </HoverCardContent>
    </HoverCard>
  )
}

// Plan-mode indicator: when the session's effective permission mode is "plan",
// the model only plans and never executes tools. Surface it so the user knows
// why nothing is running until they approve the plan (ExitPlanMode).
function PlanModeBadge({ session }: { session: SessionViewModel }) {
  const t = useTranslations("dashboard.session")
  const settings = session.runtimeSettings as { permissionMode?: unknown } | null | undefined
  if (!settings || settings.permissionMode !== "plan") return null
  return (
    <Badge variant="secondary" className="shrink-0 cursor-default font-normal">
      {t("planMode")}
    </Badge>
  )
}

function TogglePanelButton({ id, icon: Icon }: { id: PanelId; icon: PanelIcon }) {
  const { panels, setPanelMode } = useWorkspace()
  const t = useTranslations("dashboard.session")
  const active = panels[id] !== "closed"
  return (
    <button
      type="button"
      aria-label={t(PANEL_META[id].titleKey)}
      onClick={() => setPanelMode(id, active ? "closed" : "docked")}
      className={cn(
        "rounded-md p-2 transition-colors hover:bg-accent hover:text-foreground",
        active ? "text-foreground" : "text-muted-foreground",
      )}
    >
      <Icon className="size-4" />
    </button>
  )
}

type SlashCommand = {
  name?: string
  description?: string
  isEnabled?: boolean
  isBuiltin?: boolean
}

function SlashCommandsSection({ sessionId }: { sessionId: string }) {
  const { session: authSession } = useAuth()
  const token = authSession?.accessToken ?? null
  const [open, setOpen] = React.useState(false)
  const [commands, setCommands] = React.useState<SlashCommand[] | null>(null)
  const [loading, setLoading] = React.useState(false)

  React.useEffect(() => {
    if (!open || commands !== null || !token) return
    let cancelled = false
    setLoading(true)
    dashboardApi.getServerInfo(token, sessionId)
      .then((resp) => {
        if (cancelled) return
        const result = resp.result as Record<string, unknown> | null | undefined
        const raw = Array.isArray(result?.commands) ? (result.commands as SlashCommand[]) : []
        setCommands(raw)
      })
      .catch(() => {
        if (!cancelled) setCommands([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [open, commands, token, sessionId])

  return (
    <div>
      <button
        type="button"
        className="flex w-full items-center justify-between py-1 text-xs font-semibold uppercase tracking-widest text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((v) => !v)}
      >
        Slash Commands
        {open ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
      </button>
      {open && (
        <div className="pt-2">
          {loading ? (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="size-3 animate-spin" />
              <span>Loading…</span>
            </div>
          ) : commands && commands.length > 0 ? (
            <div className="space-y-1">
              {commands.filter((c) => c.isEnabled !== false).map((cmd, i) => (
                <div key={cmd.name ?? i} className="grid grid-cols-[100px_minmax(0,1fr)] gap-x-3 text-xs">
                  <span className="code-mono truncate font-medium text-foreground">{cmd.name}</span>
                  <span className="truncate text-muted-foreground">{cmd.description ?? ""}</span>
                </div>
              ))}
            </div>
          ) : commands !== null ? (
            <p className="text-xs text-muted-foreground">No commands available</p>
          ) : null}
        </div>
      )}
    </div>
  )
}
