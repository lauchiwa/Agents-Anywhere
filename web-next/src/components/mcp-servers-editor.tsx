"use client"

import React from "react"
import { Loader2, Plus, Trash2, X } from "lucide-react"
import { useTranslations } from "next-intl"

import { useAuth } from "@/components/auth/auth-context"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Textarea } from "@/components/ui/textarea"
import { dashboardApi } from "@/features/dashboard/api"
import type { McpServerConfig, McpServersMap, McpServerType } from "@/features/dashboard/types"
import { cn } from "@/lib/utils"

// ── Draft types ────────────────────────────────────────────────────────────────

type KVPair = { k: string; v: string }

type McpServerDraft = {
  _id: string
  name: string
  type: McpServerType
  // stdio
  command: string
  argsText: string
  env: KVPair[]
  // http / sse
  url: string
  headers: KVPair[]
}

// ── Conversion helpers ─────────────────────────────────────────────────────────

function newDraft(): McpServerDraft {
  return {
    _id: crypto.randomUUID(),
    name: "",
    type: "stdio",
    command: "",
    argsText: "",
    env: [],
    url: "",
    headers: [],
  }
}

function configToDraft(name: string, config: McpServerConfig): McpServerDraft {
  return {
    _id: crypto.randomUUID(),
    name,
    type: config.type,
    command: config.command ?? "",
    argsText: (config.args ?? []).join("\n"),
    env: Object.entries(config.env ?? {}).map(([k, v]) => ({ k, v })),
    url: config.url ?? "",
    headers: Object.entries(config.headers ?? {}).map(([k, v]) => ({ k, v })),
  }
}

function draftToConfig(draft: McpServerDraft): McpServerConfig {
  if (draft.type === "stdio") {
    const args = draft.argsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean)
    const env = Object.fromEntries(draft.env.filter((p) => p.k.trim()).map((p) => [p.k, p.v]))
    return {
      type: "stdio",
      command: draft.command.trim() || undefined,
      ...(args.length > 0 && { args }),
      ...(Object.keys(env).length > 0 && { env }),
    }
  }
  const headers = Object.fromEntries(
    draft.headers.filter((p) => p.k.trim()).map((p) => [p.k, p.v]),
  )
  return {
    type: draft.type,
    url: draft.url.trim() || undefined,
    ...(Object.keys(headers).length > 0 && { headers }),
  }
}

function mapToDrafts(map: McpServersMap): McpServerDraft[] {
  return Object.entries(map).map(([name, config]) => configToDraft(name, config))
}

function draftsToMap(drafts: McpServerDraft[]): McpServersMap {
  return Object.fromEntries(drafts.map((d) => [d.name.trim(), draftToConfig(d)]))
}

// ── Validation ─────────────────────────────────────────────────────────────────

function validateDrafts(drafts: McpServerDraft[], t: ReturnType<typeof useTranslations>): string | null {
  const names = drafts.map((d) => d.name.trim())
  if (names.some((n) => !n)) return t("nameRequired")
  if (new Set(names).size !== names.length) return t("nameUnique")
  for (const d of drafts) {
    if (d.type === "stdio" && !d.command.trim()) return `${t("commandRequired")}: ${d.name}`
    if ((d.type === "http" || d.type === "sse") && !d.url.trim())
      return `${t("urlRequired")}: ${d.name}`
  }
  return null
}

// ── KV pair list ───────────────────────────────────────────────────────────────

function KVList({
  pairs,
  addLabel,
  onChange,
}: {
  pairs: KVPair[]
  addLabel: string
  onChange: (pairs: KVPair[]) => void
}) {
  return (
    <div className="space-y-1.5">
      {pairs.map((pair, i) => (
        <div key={i} className="flex items-center gap-1.5">
          <Input
            placeholder="KEY"
            value={pair.k}
            onChange={(e) => {
              const next = pairs.map((p, j) => (j === i ? { ...p, k: e.target.value } : p))
              onChange(next)
            }}
            className="h-7 flex-1 text-xs"
          />
          <span className="shrink-0 text-xs text-muted-foreground">=</span>
          <Input
            placeholder="value"
            value={pair.v}
            onChange={(e) => {
              const next = pairs.map((p, j) => (j === i ? { ...p, v: e.target.value } : p))
              onChange(next)
            }}
            className="h-7 flex-1 text-xs"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-7 shrink-0 text-muted-foreground"
            onClick={() => onChange(pairs.filter((_, j) => j !== i))}
          >
            <X className="size-3" />
          </Button>
        </div>
      ))}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 gap-1 px-2 text-xs text-muted-foreground"
        onClick={() => onChange([...pairs, { k: "", v: "" }])}
      >
        <Plus className="size-3" />
        {addLabel}
      </Button>
    </div>
  )
}

// ── Server card ────────────────────────────────────────────────────────────────

const TYPES: McpServerType[] = ["stdio", "http", "sse"]

function McpServerCard({
  draft,
  onUpdate,
  onDelete,
}: {
  draft: McpServerDraft
  onUpdate: (d: McpServerDraft) => void
  onDelete: () => void
}) {
  const t = useTranslations("dashboard.mcp")
  const set = <K extends keyof McpServerDraft>(key: K, val: McpServerDraft[K]) =>
    onUpdate({ ...draft, [key]: val })

  return (
    <div className="space-y-3 rounded-xl border border-border bg-card/60 p-3">
      {/* Name + delete */}
      <div className="flex items-center gap-2">
        <Input
          placeholder={t("serverName")}
          value={draft.name}
          onChange={(e) => set("name", e.target.value)}
          className="h-8 flex-1 text-sm font-medium"
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
          onClick={onDelete}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>

      {/* Type selector */}
      <div className="flex gap-1">
        {TYPES.map((tp) => (
          <button
            key={tp}
            type="button"
            onClick={() => {
              onUpdate({ ...draft, type: tp })
            }}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              draft.type === tp
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:bg-muted/80",
            )}
          >
            {tp}
          </button>
        ))}
      </div>

      {/* Conditional fields */}
      {draft.type === "stdio" ? (
        <div className="space-y-2.5">
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">{t("command")}</Label>
            <Input
              placeholder="npx my-mcp-server"
              value={draft.command}
              onChange={(e) => set("command", e.target.value)}
              className="h-8 font-mono text-xs"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">{t("args")}</Label>
            <Textarea
              placeholder={"--arg1\n--arg2"}
              value={draft.argsText}
              onChange={(e) => set("argsText", e.target.value)}
              className="min-h-14 resize-none font-mono text-xs"
              rows={2}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">{t("env")}</Label>
            <KVList
              pairs={draft.env}
              addLabel={t("addEnv")}
              onChange={(pairs) => set("env", pairs)}
            />
          </div>
        </div>
      ) : (
        <div className="space-y-2.5">
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">{t("url")}</Label>
            <Input
              placeholder="https://example.com/mcp"
              value={draft.url}
              onChange={(e) => set("url", e.target.value)}
              className="h-8 font-mono text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">{t("headers")}</Label>
            <KVList
              pairs={draft.headers}
              addLabel={t("addHeader")}
              onChange={(pairs) => set("headers", pairs)}
            />
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export function McpServersEditor({
  scope,
  scopeId,
  readOnly = false,
}: {
  scope: "connector" | "session"
  scopeId: string
  readOnly?: boolean
}) {
  const t = useTranslations("dashboard.mcp")
  const { session: authSession } = useAuth()
  const token = authSession?.accessToken ?? null

  const [drafts, setDrafts] = React.useState<McpServerDraft[]>([])
  const [original, setOriginal] = React.useState<McpServersMap>({})
  const [loading, setLoading] = React.useState(true)
  const [loadError, setLoadError] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [saveError, setSaveError] = React.useState<string | null>(null)
  const [validationError, setValidationError] = React.useState<string | null>(null)

  const load = React.useCallback(async () => {
    if (!token) return
    setLoading(true)
    setLoadError(false)
    try {
      const resp =
        scope === "connector"
          ? await dashboardApi.getConnectorMcpServers(token, scopeId)
          : await dashboardApi.getSessionMcpServers(token, scopeId)
      setOriginal(resp.mcpServers ?? {})
      setDrafts(mapToDrafts(resp.mcpServers ?? {}))
    } catch {
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }, [scope, scopeId, token])

  React.useEffect(() => {
    void load()
  }, [load])

  const handleSave = async () => {
    const err = validateDrafts(drafts, t)
    if (err) {
      setValidationError(err)
      return
    }
    setValidationError(null)
    if (!token) return
    setSaving(true)
    setSaveError(null)
    try {
      const map = draftsToMap(drafts)
      const resp =
        scope === "connector"
          ? await dashboardApi.putConnectorMcpServers(token, scopeId, map)
          : await dashboardApi.putSessionMcpServers(token, scopeId, map)
      setOriginal(resp.mcpServers ?? {})
      setDrafts(mapToDrafts(resp.mcpServers ?? {}))
    } catch {
      setSaveError(t("saveFailed"))
    } finally {
      setSaving(false)
    }
  }

  const addServer = () => {
    setDrafts((prev) => [...prev, newDraft()])
    setValidationError(null)
  }

  const updateDraft = (id: string, updated: McpServerDraft) => {
    setDrafts((prev) => prev.map((d) => (d._id === id ? updated : d)))
    setValidationError(null)
  }

  const deleteDraft = (id: string) => {
    setDrafts((prev) => prev.filter((d) => d._id !== id))
    setValidationError(null)
  }

  const isDirty =
    JSON.stringify(draftsToMap(drafts)) !== JSON.stringify(original)

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="size-4 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="space-y-2 py-4 text-center">
        <p className="text-sm text-muted-foreground">{t("loadFailed")}</p>
        <Button type="button" variant="ghost" size="sm" onClick={() => void load()}>
          Retry
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {drafts.length === 0 ? (
        <p className="py-2 text-center text-xs text-muted-foreground">{t("noServers")}</p>
      ) : (
        <div className="space-y-2">
          {drafts.map((draft) => (
            <McpServerCard
              key={draft._id}
              draft={draft}
              onUpdate={(updated) => updateDraft(draft._id, updated)}
              onDelete={() => deleteDraft(draft._id)}
            />
          ))}
        </div>
      )}

      {!readOnly && (
        <>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 w-full gap-1.5 border border-dashed border-border text-xs text-muted-foreground hover:text-foreground"
            onClick={addServer}
          >
            <Plus className="size-3.5" />
            {t("addServer")}
          </Button>

          {(validationError ?? saveError) && (
            <p className="text-xs text-destructive">{validationError ?? saveError}</p>
          )}

          <Separator />

          <Button
            type="button"
            size="sm"
            className="w-full"
            disabled={!isDirty || saving}
            onClick={() => void handleSave()}
          >
            {saving ? (
              <>
                <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                {t("saving")}
              </>
            ) : (
              t("save")
            )}
          </Button>
        </>
      )}
    </div>
  )
}
