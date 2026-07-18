# Android 主页会话列表搜索

## Goal

`HomeHeader` 的 Search 按钮目前只弹 "coming soon" 提示。与 Web sidebar 搜索对称，实现内联搜索：点击图标展开搜索框，实时过滤会话列表（title / tag / cwd basename）。

## Requirements

1. 点击 Search 按钮：wordmark 收起，原位展开 `BasicTextField` 并自动获得焦点。
2. 键入内容实时过滤 Active / Archived 会话（title、tag、cwd basename，任意命中即显示）。
3. 点击清除按钮（X）或输入框失焦且内容为空时，收起搜索框恢复 wordmark，清空 query。
4. 搜索激活时 pinned 区和普通区均过滤。
5. 过滤逻辑纯前端，不发网络请求。
6. 添加字符串资源：`home_search_placeholder`（EN/ZH）；移除或替换 `home_search_coming_soon`。

## Acceptance Criteria

- [ ] 点击 Search 展开内联输入框，wordmark 隐藏
- [ ] 输入文字后会话列表实时过滤（title/tag/cwd basename）
- [ ] 点 X 清除并收起
- [ ] `./gradlew :app:compileDebugKotlin` 通过
