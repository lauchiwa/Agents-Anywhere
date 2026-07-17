# Implement Plan: 全面项目审计

## Execution Strategy

并行三路审计 subagent，每路聚焦不同代码层，最后综合发现并修复 P0/P1。

## Checklist

- [ ] 1. 激活任务（task.py start）
- [ ] 2. 派发 trellis-check subagent × 3（server / connector / frontend+android）
- [ ] 3. 汇总所有 finding，按 severity 分级
- [ ] 4. 修复 P0/P1 问题
- [ ] 5. 运行全量测试验证无回归
- [ ] 6. 更新 prd.md P2/P3 backlog
- [ ] 7. 提交并归档

## Validation Commands

```bash
# Server tests
cd server && python -m pytest tests/ -x -q 2>&1 | tail -5

# Connector tests
cd connector && python -m pytest tests/ -x -q 2>&1 | tail -5
```

## Rollback Points

- 每次修复前确认 git status clean（修复已有基础上）
- 如发现修复导致测试失败，立即 git diff 查看变更并回滚该文件
