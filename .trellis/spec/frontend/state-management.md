# 状态管理

> 本地状态、服务端状态与派生状态的约定，取证自 `web-next/src/`。

## 没有全局状态库，以本地状态 + Context 为主

项目不使用 Redux / Zustand / Jotai。状态分三类：

- **本地组件状态**：`useState` / `useReducer`，绝大多数交互状态属于这一类。
- **跨子树共享状态**：React Context，例如 `components/workspace-context.tsx`、`components/theme-provider.tsx`。需要被一棵子树共享时才上升到 Context，不要一上来就全局化。
- **服务端状态**：不缓存到全局 store，由具体组件用 `useState` + `useEffect` 拉取并持有（见 Hook 规范）。

## 派生状态用 `useMemo`，不要另存一份 state

从已有数据算出来的东西一律 `useMemo` 现算，不要用 `useEffect` 同步进一个新的 `useState`——那样会引入两份真相和额外一次渲染。

时间线的分组与父子归属就是范例：

```tsx
const groups = React.useMemo(
  () => groupTimelineItems(state?.items ?? [], approvalTargetIds),
  [approvalTargetIds, state?.items],
)
const childrenByParent = React.useMemo(
  () => buildChildrenByParent(state?.items ?? []),
  [state?.items],
)
```

参考文件：`web-next/src/components/session-detail.tsx`。

## 服务端状态的增量合并

时间线通过 `afterSeq` / `beforeOrderSeq` 增量拉取（见 `DashboardApi` 的 `SessionStateQuery`），本地对乐观消息与服务端条目做合并/去重，逻辑集中在 `components/session/optimistic-timeline.ts`。新增“本地先行、服务端后到”的场景时复用这里，不要在组件里散落合并逻辑。

参考文件：`web-next/src/components/session/optimistic-timeline.ts`、`web-next/src/features/dashboard/api.ts`。

## 常见错误

- 用 `useEffect` 把 props/state 拷进另一个 `useState` 来做“派生” → 改用 `useMemo`。
- 把只有一个子树需要的状态提升成全局/顶层 Context，放大重渲染范围。
- 在多个组件里各写一份时间线去重逻辑 → 收敛到 `optimistic-timeline.ts`。
