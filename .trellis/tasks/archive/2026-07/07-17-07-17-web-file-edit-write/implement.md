# 实现计划：Web 文件面板远程编辑回写

## 现状分析

**后端全链已就绪，无需改动：**
- `dashboardApi.connectorFsWrite(token, connectorId, root, {path, content, ifMatch?})` — `api.ts:337`
- `FsReadTextResult.sha256` — `types.ts:339`（打开文件时拿到）
- `FsWriteResult` — `types.ts:373`
- 服务端 `POST /connectors/{id}/fs/write` — 已有
- 连接器 `fs.writeFile` RPC（含 ifMatch 乐观锁）— 已有

**前端已有：**
- `MonacoCodeView` — `components/monaco-code-view.tsx`，已有 `editable` + `onChange` props
- `openNativeFilePreviewWindow()` — `files-panel.tsx:319`，打开弹窗预览（只读）

**需要改动：**
- `files-panel.tsx` — 打开弹窗时传递写回能力（或改为内嵌 sheet 模式）
- `file-preview-page.tsx` — 预览页目前是否支持编辑？需查

**架构决策**：
文件预览走弹窗窗口（`window.open`）方式，token 不跨窗口传递。
最简实现：**在文件面板内直接内嵌 Sheet/Dialog**，用 `MonacoCodeView editable` 显示+编辑，保存按钮调 `connectorFsWrite`。
不改弹窗预览页（那是无 token 的 public preview）。

## 实现步骤

### Step 1: 确认 files-panel 调用链

读 `files-panel.tsx` 全文，确认：
- `token`, `connectorId`, `root` 怎么传入
- 下载/预览是哪个入口，确认可以在同一入口处增加"在面板内内嵌编辑"逻辑
- 上下文菜单项（`ContextMenuItem`）有哪些

### Step 2: 增加 i18n keys

在 `web-next/messages/en.json` 和 `zh-CN.json` 中增加：
- `"fileEdit"` — "Edit"  / "编辑"
- `"fileSave"` — "Save"  / "保存"
- `"fileSaving"` — "Saving..." / "保存中..."
- `"fileSaved"` — "Saved" / "已保存"
- `"fileConflict"` — "File was modified on device. Overwrite?" / "文件已在设备上被修改，是否覆盖？"
- `"fileConflictConfirm"` — "Overwrite" / "强制覆盖"

### Step 3: 在 files-panel 增加 inline 编辑 Sheet

在 `files-panel.tsx` 中：

1. 增加 state：
   ```ts
   const [editFile, setEditFile] = useState<{path: string; content: string; sha256: string} | null>(null)
   const [editValue, setEditValue] = useState("")
   const [editDirty, setEditDirty] = useState(false)
   const [saving, setSaving] = useState(false)
   const [savedFlash, setSavedFlash] = useState(false)
   ```

2. 上下文菜单增加"编辑"项（仅文本文件、`contextIsFile`）：
   ```tsx
   <ContextMenuItem onSelect={() => void openEditor(contextEntry)}>
     {t("fileEdit")}
   </ContextMenuItem>
   ```

3. `openEditor(entry)` 函数：
   - 调 `dashboardApi.connectorFsReadText(token, connectorId, root, {path: entry.path, maxBytes: 2*1024*1024})`
   - 成功后 `setEditFile({path, content, sha256})`，`setEditValue(content)`，`setEditDirty(false)`

4. 渲染 Sheet（Radix `<Sheet>`）：
   ```tsx
   <Sheet open={!!editFile} onOpenChange={open => !open && setEditFile(null)}>
     <SheetContent side="right" className="w-[80vw] max-w-[900px] flex flex-col">
       <SheetHeader>
         <SheetTitle>{editFile?.path}</SheetTitle>
       </SheetHeader>
       <MonacoCodeView
         content={editValue}
         fileName={editFile?.path ?? ""}
         editable
         onChange={v => { setEditValue(v); setEditDirty(true) }}
         className="flex-1 min-h-0"
       />
       <div className="flex justify-end gap-2 py-2">
         {savedFlash && <span className="text-sm text-green-600">{t("fileSaved")}</span>}
         <Button disabled={!editDirty || saving} onClick={() => void handleSave(false)}>
           {saving ? t("fileSaving") : t("fileSave")}
         </Button>
       </div>
     </SheetContent>
   </Sheet>
   ```

5. `handleSave(force: boolean)` 函数：
   ```ts
   async function handleSave(force: boolean) {
     if (!editFile || !token || !connectorId) return
     setSaving(true)
     try {
       const res = await dashboardApi.connectorFsWrite(token, connectorId, root, {
         path: editFile.path,
         content: editValue,
         ifMatch: force ? undefined : editFile.sha256,
       })
       if (!res.ok && res.error?.status === 409) {
         // 冲突：弹确认
         if (window.confirm(t("fileConflict"))) {
           await handleSave(true)
         }
         return
       }
       if (!res.ok) throw new Error(res.error?.message ?? "write failed")
       // 更新 sha256
       setEditFile(prev => prev ? {...prev, sha256: res.result?.sha256 ?? prev.sha256} : prev)
       setEditDirty(false)
       setSavedFlash(true)
       setTimeout(() => setSavedFlash(false), 2000)
     } catch (e) {
       toast.error(String(e))
     } finally {
       setSaving(false)
     }
   }
   ```

6. Cmd/Ctrl+S 快捷键：在 Sheet 容器的 `onKeyDown` 中捕获 `(e.metaKey || e.ctrlKey) && e.key === 's'`。

### Step 4: 检查 toast 导入

确认 `files-panel.tsx` 已有 toast（Sonner/Radix）；如无，使用项目已有 toast 方案（同 `session-tool-cards.tsx`）。

### Step 5: TypeScript 检查

```bash
cd web-next && npx tsc --noEmit 2>&1 | head -50
```

修复所有类型错误。

## 验证命令

```bash
# TypeScript 检查
cd /Users/chivarlau/Work/workspace/PythonProjects/Agents-Anywhere/web-next
npx tsc --noEmit

# 本地开发服务器手动测试
# 1. 在文件面板右键文本文件 → 编辑
# 2. 修改内容 → 保存 → 确认设备文件已更新
# 3. 在设备上修改文件 → Web 端再次保存 → 确认 409 冲突弹窗出现
```

## 不做的事

- 不改 `file-preview-page.tsx`（无 token，只读）
- 不加新建/删除/重命名文件
- 不做 Android 文件编辑
