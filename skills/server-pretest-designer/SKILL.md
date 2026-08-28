---
name: server-pretest-designer
description: 根据需求文档和 SunnyIsland 服务端代码设计服务器先行测试用例，梳理请求、Actor、Diff、持久化与异常恢复链路，并产出可自动执行、可定位问题的用例定义。
---

# Server Pretest Designer

## 工作顺序

1. 从需求文档提取状态、触发条件、数值、奖励、失败、幂等和恢复规则；未确认规则标记为待确认。
2. 从协议入口追踪 Gate → Garden → Actor → 业务子模块 → Redis/Mongo/事件 → 响应与 Actor Diff。
3. 为每条规则记录代码符号、配置键、Actor 字段、可观测结果和风险。
4. 先设计最小主流程，再补边界、重复请求、断线重连、Actor 释放恢复、保存失败和配置缺失。
5. 将用例保存到 `cases/*.json`；业务预期写入断言，不写死在执行器中。
6. 用例评审：由测试、产品和开发（按需求影响范围）检查覆盖、前置条件、数据影响、断言可观测性和失败定位信息。
7. 根据评审意见迭代用例；保留评审意见、修改内容和版本号，迭代完成后再标记为可执行。

## 评审门禁

用例文件应包含 `review.status`：

- `draft`：刚编写，禁止进入正式批量执行；
- `in_review`：等待评审；
- `changes_requested`：评审提出修改，必须迭代；
- `approved`：评审通过，可执行。

同时记录 `review.reviewer`、`review.reviewed_at`、`review.comments` 和 `review.iteration`。评审不是走过场：每条意见都要能对应到用例步骤、断言或数据准备变化。

## 用例要求

每个用例包含：`id`、`name`、`preconditions`、`steps`、`assertions`。步骤必须说明输入和保存的输出；断言应指向响应、Actor、Diff 或持久化字段。

每条用例同时记录：测试目标、数据影响、清理方式、关键服务端模块和失败时应搜索的日志关键词。禁止直接删除或修改 Redis/Mongo Actor 数据来让用例通过。
