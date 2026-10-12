# Extra Practice Implementation Plan

**Goal:** 结果页单遍加练，保留固定基准并展示可试听的变化。

**Architecture:** 复用现有录音提交接口，新增独立前端会话/比较模块。反馈数据增加稳定问题标识和逐遍问题/不可比较索引。原轮与加练轮分别保存，比较只在当前页维护。

**Tech Stack:** Python/FastAPI, vanilla JavaScript, pytest, node:test.

- [x] 在 tests/js/extra-practice.test.cjs 验证固定基准、单遍结论、连续加练和不可靠词。
- [x] 增加 web/view.py 逐遍比较数据及 app.py 汇总问题标识，验证反馈接口。
- [x] 新增 static/extra-practice.js，连接 app.js 单遍录音入口、结果保留及试听。
- [x] 更新样式、README，执行 Python 和 JavaScript 测试以及语法检查。
- [ ] 审查差异后提交并推送。
