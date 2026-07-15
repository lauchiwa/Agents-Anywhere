# rate limit 限流事件展示

## Goal

SDK 有完整的 `RateLimitEvent` / `RateLimitInfo`（额度类型、利用率、重置时间、超额），CLI 在限流状态变化时主动 emit。连接器 `_receive_response` 无任何对 rate-limit 消息的分支——用户被限流卡住时看不到原因，只感觉“卡了”。

## Background（调研结论）

- 类型：`RateLimitEvent` / `RateLimitInfo`（utilization、resets_at、overage_* + raw）/ `RateLimitStatus`（"allowed"|"allowed_warning"|"rejected"）/ `RateLimitType`（"five_hour"|"seven_day"|"seven_day_opus"|"seven_day_sonnet"|"overage"）。
- 当前 `_receive_response`（sdk_adapter.py:304）只处理 stream/assistant/user/result，system 分支直接 `continue`，rate-limit 事件在其中被吞掉。

## Requirements

- 在 `_receive_response` 识别 rate-limit 消息类型（类名匹配，与现有 `_is_result_message` 等一致的脆弱但一致的风格）。
- 将限流状态转成一个轻量通知/系统时间线项或 session 级状态字段：至少含 status、type、resets_at。
- 客户端在 `allowed_warning` / `rejected` 时给出可见提示（"额度将满，X 时重置" / "已被限流"）。
- 状态恢复（重新 allowed）时清除提示。

## Acceptance Criteria

- [ ] rate-limit 消息不再被 system 分支静默丢弃。
- [ ] 限流状态可下发到客户端并展示（含重置时间）。
- [ ] `rejected` 状态与普通 turn 失败在 UI 上可区分。
- [ ] 连接器测试覆盖 rate-limit 解析路径。

## Notes

- 优先级 P2。
- 依赖真实限流场景较难本地复现，测试以构造 fake 消息为主。
