"use client"

import * as React from "react"
import { Check, Loader2, Map, MessageCircleQuestion, ShieldCheck, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type {
  Approval,
  ApprovalQuestion,
  ApprovalResolveStatus,
  ApprovalSelection,
} from "@/features/dashboard/types"
import { useTranslations } from "next-intl"

type ApprovalCardProps = {
  approval: Approval
  resolvingApprovalId: string | null
  resolvingStatus: ApprovalResolveStatus | null
  onResolveApproval: (
    approvalId: string,
    status: ApprovalResolveStatus,
    selections?: ApprovalSelection[],
  ) => void
  compact?: boolean
}

// The `__other__` sentinel marks the free-text "Other" option the CLI always
// appends; its real value comes from the text input rather than the label.
const OTHER_VALUE = "__other__"

// Pull the questions array out of the loosely-typed approval payload
// ({toolName, input: {questions: [...]}}). Returns [] for non-question cards.
// `options` is normalized to an array so QuestionCard's `q.options.map` never
// throws on malformed payloads (the connector forwards the input as-is).
function readQuestions(payload: unknown): ApprovalQuestion[] {
  if (!payload || typeof payload !== "object") return []
  const input = (payload as { input?: unknown }).input
  if (!input || typeof input !== "object") return []
  const questions = (input as { questions?: unknown }).questions
  if (!Array.isArray(questions)) return []
  return questions
    .filter(
      (q): q is ApprovalQuestion =>
        !!q && typeof q === "object" && typeof (q as ApprovalQuestion).question === "string",
    )
    .map((q) => ({
      ...q,
      options: Array.isArray(q.options)
        ? q.options.filter(
            (opt): opt is ApprovalQuestion["options"][number] =>
              !!opt && typeof opt === "object" && typeof opt.label === "string",
          )
        : [],
    }))
}

export function ApprovalCard(props: ApprovalCardProps) {
  const { approval } = props
  if (approval.kind === "question" || approval.choices.includes("answer")) {
    return <QuestionCard {...props} />
  }
  return <PermissionCard {...props} />
}

function PermissionCard({
  approval,
  resolvingApprovalId,
  resolvingStatus,
  onResolveApproval,
  compact,
}: ApprovalCardProps) {
  const tSession = useTranslations("dashboard.session")
  const resolving = resolvingApprovalId === approval.id
  const disabled = resolvingApprovalId !== null
  const toolName = (approval.payload as { toolName?: string } | null)?.toolName ?? ""
  const isPlanMode = toolName === "EnterPlanMode" || toolName === "ExitPlanMode"
  const CardIcon = isPlanMode ? Map : ShieldCheck
  return (
    <div className={cn("rounded-xl border border-border bg-muted/25 p-3", compact && "rounded-lg")}>
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <div className="flex min-w-0 gap-2">
          <CardIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <div className="wrap-break-word text-sm font-medium">{approval.title || tSession("approvalRequested")}</div>
            {approval.description ? (
              <p className="mt-0.5 wrap-break-word text-sm text-muted-foreground">{approval.description}</p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap justify-end gap-2 md:flex-nowrap">
          {approval.choices.includes("reject") ? (
            <Button
              variant="outline"
              size="sm"
              className="whitespace-nowrap"
              disabled={disabled}
              onClick={() => onResolveApproval(approval.id, "rejected")}
            >
              {resolving && resolvingStatus === "rejected" ? <Loader2 className="size-3.5 animate-spin" /> : <X className="size-3.5" />}
              {tSession("reject")}
            </Button>
          ) : null}
          {approval.choices.includes("approve_for_session") ? (
            <Button
              variant="outline"
              size="sm"
              className="whitespace-nowrap"
              disabled={disabled}
              onClick={() => onResolveApproval(approval.id, "approved_for_session")}
            >
              {resolving && resolvingStatus === "approved_for_session" ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />}
              {tSession("approveSession")}
            </Button>
          ) : null}
          {approval.choices.includes("approve") ? (
            <Button
              size="sm"
              className="whitespace-nowrap"
              disabled={disabled}
              onClick={() => onResolveApproval(approval.id, "approved")}
            >
              {resolving && resolvingStatus === "approved" ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
              {tSession("approve")}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function QuestionCard({
  approval,
  resolvingApprovalId,
  onResolveApproval,
  compact,
}: ApprovalCardProps) {
  const tSession = useTranslations("dashboard.session")
  const questions = React.useMemo(() => readQuestions(approval.payload), [approval.payload])
  const disabled = resolvingApprovalId !== null
  const resolving = resolvingApprovalId === approval.id

  // Per-question selection: chosen option labels (multi allows several) plus the
  // free-text value typed into the "Other" input, kept separately so toggling
  // "Other" off doesn't lose what was typed.
  const [selected, setSelected] = React.useState<Record<number, string[]>>({})
  const [otherText, setOtherText] = React.useState<Record<number, string>>({})

  const toggleOption = (qIndex: number, label: string, multi: boolean) => {
    setSelected((prev) => {
      const current = prev[qIndex] ?? []
      if (multi) {
        const next = current.includes(label)
          ? current.filter((l) => l !== label)
          : [...current, label]
        return { ...prev, [qIndex]: next }
      }
      return { ...prev, [qIndex]: current.includes(label) ? [] : [label] }
    })
  }

  // Resolve each question's chosen labels, substituting the typed text for the
  // "Other" sentinel. Questions with no selection are omitted.
  const buildSelections = (): ApprovalSelection[] => {
    const result: ApprovalSelection[] = []
    questions.forEach((q, qIndex) => {
      const chosen = selected[qIndex] ?? []
      const labels = chosen
        .map((label) => (label === OTHER_VALUE ? (otherText[qIndex] ?? "").trim() : label))
        .filter((label) => label.length > 0)
      if (labels.length > 0) {
        result.push({ question: q.question, labels })
      }
    })
    return result
  }

  const selections = buildSelections()
  // Every question must have at least one answer before submitting.
  const canSubmit = questions.length > 0 && selections.length === questions.length

  const handleSubmit = () => {
    if (!canSubmit || disabled) return
    onResolveApproval(approval.id, "approved", selections)
  }

  return (
    <div className={cn("rounded-xl border border-border bg-muted/25 p-3", compact && "rounded-lg")}>
      <div className="flex min-w-0 gap-2">
        <MessageCircleQuestion className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="wrap-break-word text-sm font-medium">
            {approval.title || tSession("approvalRequested")}
          </div>

          <div className="mt-2 flex flex-col gap-4">
            {questions.map((q, qIndex) => {
              const multi = q.multiSelect === true
              const chosen = selected[qIndex] ?? []
              const otherActive = chosen.includes(OTHER_VALUE)
              return (
                <div key={qIndex} className="flex flex-col gap-1.5">
                  {q.header ? (
                    <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {q.header}
                    </div>
                  ) : null}
                  <div className="wrap-break-word text-sm">{q.question}</div>
                  <div className="mt-1 flex flex-col gap-1.5">
                    {q.options.map((opt) => {
                      const active = chosen.includes(opt.label)
                      return (
                        <button
                          key={opt.label}
                          type="button"
                          disabled={disabled}
                          onClick={() => toggleOption(qIndex, opt.label, multi)}
                          className={cn(
                            "flex flex-col items-start gap-0.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                            active
                              ? "border-primary bg-primary/10"
                              : "border-border bg-background hover:bg-accent",
                            disabled && "opacity-60",
                          )}
                        >
                          <span className="wrap-break-word font-medium">{opt.label}</span>
                          {opt.description ? (
                            <span className="wrap-break-word text-xs text-muted-foreground">
                              {opt.description}
                            </span>
                          ) : null}
                        </button>
                      )
                    })}
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => toggleOption(qIndex, OTHER_VALUE, multi)}
                      className={cn(
                        "rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                        otherActive
                          ? "border-primary bg-primary/10"
                          : "border-border bg-background hover:bg-accent",
                        disabled && "opacity-60",
                      )}
                    >
                      {tSession("answerOther")}
                    </button>
                    {otherActive ? (
                      <input
                        type="text"
                        autoFocus
                        disabled={disabled}
                        value={otherText[qIndex] ?? ""}
                        onChange={(e) =>
                          setOtherText((prev) => ({ ...prev, [qIndex]: e.target.value }))
                        }
                        placeholder={tSession("answerOtherPlaceholder")}
                        className="rounded-lg border border-border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                      />
                    ) : null}
                  </div>
                </div>
              )
            })}
          </div>

          <div className="mt-3 flex flex-wrap justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              className="whitespace-nowrap"
              disabled={disabled}
              onClick={() => onResolveApproval(approval.id, "rejected")}
            >
              {tSession("answerSkip")}
            </Button>
            <Button
              size="sm"
              className="whitespace-nowrap"
              disabled={disabled || !canSubmit}
              onClick={handleSubmit}
            >
              {resolving ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
              {tSession("answerSubmit")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function ApprovalHeaderNotice({
  pendingApprovalCount,
  onResolveClick,
}: {
  pendingApprovalCount: number
  onResolveClick: () => void
}) {
  const tSession = useTranslations("dashboard.session")

  return (
    <div className="pointer-events-none absolute inset-x-0 top-14 z-20 px-4 pt-2">
      <div className="mx-auto flex w-full max-w-3xl items-center justify-between gap-3 rounded-2xl border border-border/70 bg-background/70 px-3 py-2 text-sm shadow-lg shadow-background/20 backdrop-blur-xl">
        <div className="flex min-w-0 items-center gap-2 text-foreground">
          <ShieldCheck className="size-4 shrink-0 text-amber-500" />
          <span className="min-w-0 truncate">
            {tSession(pendingApprovalCount > 1 ? "approvalPendingPlural" : "approvalPending", {
              count: pendingApprovalCount,
            })}
          </span>
        </div>
        <button
          type="button"
          className="pointer-events-auto shrink-0 rounded-full px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          onClick={onResolveClick}
        >
          {tSession("resolveBelow")}
        </button>
      </div>
    </div>
  )
}
