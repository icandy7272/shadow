# Append Takes Implementation Plan

**Goal:** 加练作为同轮的第 4、5…遍，统一沿用现有交互。

**Architecture:** app.js 保留最后成功的 run_id，追加单遍并沿用示范设置；app.py 验证归属，合并旧录音重新汇总，只保存新路径。UUID 提交编号防止网络重交重复追加。移除单独前后对比模块。

**Tech Stack:** FastAPI, vanilla JavaScript, pytest, node:test.

- [x] 先验证追加端点从 3 遍到 4、5 遍、重交去重、只保存同一轮。
- [x] 改造录音入口、连续编号和原结果渲染，移除独立对比模块。
- [x] 沿用原示范播放次数并验证设置不被改写。
- [x] 全量验证与差异检查：547 项 Python、20 项前端测试通过。

发布：按项目工作流提交并推送此功能。
