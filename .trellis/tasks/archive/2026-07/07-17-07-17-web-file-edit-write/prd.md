# Web 文件面板：远程编辑回写

## 背景

被控设备的文件系统已全链可读（浏览/预览/下载），但无法从 Web 端修改文件。后端全链已就绪：
- 连接器 `fs.writeFile` RPC（含 `ifMatch` sha256 乐观锁）
- 服务端 `POST /connectors/{id}/fs/write` API
- Web `dashboardApi.connectorFsWrite()` 方法

只差 UI 入口——把只读预览升级为可编辑并保存。

## Requirements

1. **文件预览面板可编辑**：当用户在文件面板打开文本文件时，编辑器切换为可编辑模式（`editable=true`），而非只读。
2. **保存操作**：编辑器内容变化后出现"保存"按钮（或 Cmd/Ctrl+S 快捷键），点击后调用 `dashboardApi.connectorFsWrite()`，写回被控设备。
3. **乐观锁冲突保护**：`ifMatch` 字段传入打开文件时的 sha256（从 `connectorFsReadText` 响应拿）；服务端返回 `409 Conflict`（文件已被修改）时，提示用户"文件已在设备上被修改，是否覆盖？"，确认后不带 `ifMatch` 再次写入。
4. **状态反馈**：保存中显示 loading；成功后短暂提示"已保存"；失败提示错误信息（toast）。
5. **只读文件不可编辑**：二进制文件、目录、`canLoad=false` 的情况保持只读，不显示保存按钮。
6. **Web 端专属**：本任务只做 Web 文件面板，Android 文件编辑暂不做。

## Acceptance Criteria

- [ ] 打开文本文件后编辑器可输入，内容变化后出现保存按钮（或 Cmd+S 触发）。
- [ ] 点击保存成功写入被控设备，Web 编辑器与设备文件内容一致。
- [ ] 文件在设备上被另一进程修改后，Web 端再次保存收到 409，弹出冲突提示；确认覆盖后写入成功。
- [ ] 二进制/不可加载文件保持只读，不出现保存按钮。
- [ ] Web TypeScript 检查通过（tsc --noEmit）。

## 范围外

- Android 文件编辑（另立任务）
- 新建/删除/重命名/移动文件
- 文件上传到被控设备
