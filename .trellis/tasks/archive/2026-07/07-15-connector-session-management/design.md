# Design: Session rename (connector → SDK → disk)

## 범위

이 태스크는 **rename** 하나만 다룬다. delete/archive는 서버 측에 이미 `set_session_archived` 가 있고 SDK 디스크 정리는 별도 태스크로 연기한다.

## 현재 rename 흐름

```
웹/Android → PATCH /sessions/{id} {title:...}
  → db.rename_session(session_id, title)   ← 서버 DB 업데이트 ✅
  → (끝)  ← SDK custom_title 업데이트 없음 ✗
```

SDK는 자체 `~/.claude/projects/.../...jsonl` 에 `custom_title` 를 보존한다. 서버 DB title과 SDK custom_title이 분기된다.

## 목표 흐름

```
PATCH /sessions/{id} {title:...}
  → db.rename_session(session_id, title)          ← 기존
  → manager.request("session.rename", params)     ← 추가 (best-effort)
     → connector dispatch "session.rename"         ← 추가
        → ClaudeSdkAdapter.rename_session(params)  ← 추가
           → sdk.rename_session(external_session_id, title, directory=cwd)
```

rename RPC 실패(connector offline, session not registered, SDK error)는 **비치명적**: DB 업데이트는 이미 완료됐고, 다음 `sync_session` 때 서버 title이 정답이므로 드리프트는 일시적.

## RPC 계약

### connector ← server

```
method: "session.rename"
params: {
  sessionId: string,          // 서버 session ID
  externalSessionId: string,  // Claude 외부 세션 ID (필수)
  title: string,              // 새 제목 (비어있지 않음)
  cwd?: string,               // 작업 디렉터리 (directory 파라미터로 전달)
  runtime: "claude"           // MCP와 마찬가지로 claude only
}
response: { ok: boolean, reason?: string }
```

### connector dispatch (runtime.py)

`dispatch("session.rename", params)` → `_resolve_adapter(params)` → adapter.`rename_session(params)`.

adapter에 메서드 없으면 `{"ok": false, "reason": "runtime does not support rename"}`.

### ClaudeSdkAdapter.rename_session

```python
async def rename_session(self, params: dict) -> dict:
    external_session_id = params.get("externalSessionId")
    title = params.get("title")
    if not external_session_id or not title:
        return {"ok": False, "reason": "externalSessionId and title required"}
    cwd = params.get("cwd")
    sdk = self._load_sdk()
    rename_fn = getattr(sdk, "rename_session", None)
    if not callable(rename_fn):
        return {"ok": False, "reason": "sdk does not support rename_session"}
    try:
        if cwd:
            rename_fn(external_session_id, title, directory=cwd)
        else:
            rename_fn(external_session_id, title)
    except Exception as exc:
        logger.debug("sdk rename_session failed ...", exc_info=True)
        return {"ok": False, "reason": str(exc)}
    return {"ok": True}
```

### server sessions.py PATCH 수정

```python
# db.rename_session 후에 추가:
if payload.title is not None and session.externalSessionId and session.connectorId:
    if manager.is_online(session.connectorId):
        try:
            await manager.request(
                session.connectorId,
                "session.rename",
                {
                    "sessionId": session_id,
                    "externalSessionId": session.externalSessionId,
                    "title": payload.title.strip(),
                    "cwd": session.cwd,
                    "runtime": session.runtime or "claude",
                },
                timeout=10,
            )
        except (ConnectorOfflineError, ConnectorRpcError):
            pass  # best-effort, DB already updated
```

## 테스트 범위

### connector 테스트 (test_claude_sdk_adapter.py)

1. `rename_session` → SDK `rename_session` 호출 확인 (with+without cwd)
2. SDK 메서드 없음 → `{"ok": False, "reason": "..."}`
3. SDK 예외 → `{"ok": False, "reason": "..."}`
4. params 누락 → `{"ok": False}`

### connector dispatch 테스트 (test_connector_runtime.py)

5. `session.rename` dispatch → claude adapter 라우팅

### server 테스트 (test_backend_mvp.py)

6. `PATCH /sessions/{id}` title 변경 시 connector online → `manager.request("session.rename", ...)` 호출됨
7. connector offline → rename RPC 건너뜀, 응답은 200

## 비고

- `rename_session_via_store` (async store 변형)는 사용하지 않는다. 연결기는 SDK의 동기 `rename_session`을 `asyncio.get_running_loop().run_in_executor`로 호출하거나, SDK가 비차단이면 직접 호출한다. SDK docs 확인 후 결정.
- `sdk.rename_session`이 동기 함수이면 직접 호출해도 무방 (역사 동기화와 동일한 패턴).
