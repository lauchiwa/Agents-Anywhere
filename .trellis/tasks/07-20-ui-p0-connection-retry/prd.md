# 两端P0：断线提示+失败重试+复制统一

## Goal

Web+Android 两端 P0 前端修复。纯前端，不动 connector 管道。三件事：
1. SSE/连接断线对用户可见（重连 banner）
2. 发送失败可重试且不丢草稿
3. 复制操作统一走带反馈的 helper

## Requirements

### R1. 断线可见（Web）
- `session-detail.tsx`：`EventSource` 非 OPEN 时当前静默降级到 3s 轮询。需跟踪 `readyState`/`onerror`，在时间线顶部渲染可感知的 banner（复用 `ui/alert`）：
  - 流断开重连中 → "实时更新已暂停，正在重连…"
  - 连接器离线（`session.connectorStatus`/meta）→ "设备离线"
- banner 恢复连接后自动消失。

### R2. 断线可见（Android）
- `SessionDetailScreen.kt`：`state.sseConnected` 已被写入但无任何 composable 读取。在 header 下方加细 banner：
  - `!sseConnected` → "正在重连…"
  - `!connectorOnline` → "设备离线"
- 复用 header 已有的 amber/red 文案配色风格。

### R3. 发送失败可重试（Web）
- `session-detail.tsx` + `session-composer.tsx`：发送失败时 optimistic item 标记 failed，但草稿已被清空导致文本丢失。
- 要求：发送确认成功前保留草稿；失败的 optimistic item 上加「重试」+「复制回输入框」操作。

### R4. 发送失败可重试（Android）
- 对齐 Web：失败气泡加重试入口，发送成功前不清 draft（`SessionComposer` / `SessionDetailScreen`）。
- 若 Android 现有实现已保留 draft，则只需补重试入口，落地前先核验现状。

### R5. 复制统一（Web）
- 所有复制走 `lib/clipboard.ts` 的 `copyText`（带成功/失败 toast）。
- 替换裸 `navigator.clipboard.writeText().catch(()=>undefined)`：`session-timeline-entry.tsx`、`session-tool-cards.tsx`、`markdown-text.tsx`。

### R6. 复制反馈（Android）
- 复制失败时给 toast 反馈（现状部分复制静默）。核验后按需补齐。

## Acceptance Criteria

- [ ] Web：拔网/断流时时间线顶部出现"重连中"banner，恢复后消失
- [ ] Android：断流/设备离线时 header 下出现对应 banner
- [ ] Web：发送失败后可一键重试，且原文本未丢
- [ ] Android：发送失败后可重试，草稿不丢
- [ ] Web：所有复制入口失败时有 toast，无静默失败路径
- [ ] Web `tsc` 通过；Android `compileReleaseKotlin` 通过
- [ ] 变更仅限前端，未触碰 connector / server

## Notes

- 分支 `fix/android-sse-hang`，推送到个人 fork，不合 main、不提 PR。
- 落地前先 Read 相关文件核验现状（尤其 Android draft 是否已保留），避免按审计假设盲改。
