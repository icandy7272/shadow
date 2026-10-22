# 跟读先于默写 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement inline with verification.

**Goal:** 盲听 → 不看字跟读 → 默写揭晓 → 可选补录。

**Architecture:** 保留现有录音与判分接口，在练习页集中控制步骤和揭晓权限。录音保存后解锁默写；默写判分或明确跳过后才显示原文、历史和录音分析。录音结果保留轮次编号供随后默写使用。恢复草稿时按已保存的判分/跳过状态恢复揭晓权限。

**Tech Stack:** FastAPI/Jinja, browser JavaScript, node:test, pytest.

- [x] 测试：修改 tests/js/mobile-navigation.test.cjs，覆盖先跟读、录音后默写、揭晓状态。
- [x] 实现：practice.html 调整步骤顺序与提示；app.js 调整解锁、录音轮次和分析后导航；mobile.js 集中同步揭晓权限、按钮与自动跳转；app.css 隐藏未揭晓内容。
- [x] 兼容：检查快捷键、跳过/自动跳过、旧草稿恢复、移动底栏、无麦克风时跳过跟读。
- [x] 文档：更新 README.md 与 DESIGN.md 的流程说明。
- [x] 验证：node --test tests/js/*.test.cjs；.venv/bin/pytest；检查差异后提交并推送。

审核补充：只有有效录音结果才进入默写；失败保留重试。有效判分或明确跳过控制揭晓，历史全对不再自动跳过。新流程带 flowVersion=2，录音完成但尚未默写的草稿跨天仍保留。使用临时数据在 390px、1280px 浏览器验证跳过路径及模拟录音完成事件后的隐藏和刷新恢复；真实麦克风不在此次浏览器验证范围。
