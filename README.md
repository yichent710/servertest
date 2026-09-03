# severtest

SunnyIsland服务器先行测试工具。当前最小闭环直接复用SunnyIsland的Protobuf、消息绑定和Actor Diff，实现里程碑2.0的真实本地请求测试。

## 当前能力

- 加载并校验里程碑活动配置；
- 按服务器规则计算果实积分；
- 计算到指定积分所需的最少果实组合；
- 生成稳定、可审计的JSON计划；
- 在输出中记录配置SHA-256，避免使用错误版本的配置；
- 提供结构化JSON日志；
- 通过`ServerAdapter`隔离业务规划和SunnyIsland私有协议。
- 通过本地Gate向Garden发送真实协议请求；
- 使用`DebugGiveHarvestReq`生成果实并从Actor Diff发现背包ID；
- 使用`SubmitMilestoneV2FruitsReq`提交果实；
- 校验提交积分、溢出积分、抽奖次数、背包扣除和奖励；
- 输出包含每一步输入与断言的JSON报告。

当前示例配置只用于验证工具流程，不代表线上数值。接入测试服前必须替换为对应环境的真实活动、果实和变异配置。

## 运行规划器

无需第三方运行依赖，要求Python 3.11或更高版本：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v

PYTHONPATH=src python3 -m severtest.cli plan \
  --config configs/examples/milestone-v2.json \
  --fruits configs/examples/fruits.json \
  --round 1 \
  --before-node 3 \
  --remaining 5
```

也可以使用`--target-score`直接指定目标积分，使用`--output reports/plan.json`保存计划。

## 运行本地端到端冒烟

前提：SunnyIsland位于相邻目录`../sunnyisland`，Docker网络`master_garden_network`、Gate和0.11.5特性Garden已启动。测试链路必须只保留一个Garden节点，避免Gate将请求路由到旧版本Garden。

测试账号和活动：

- UID：`10000912`
- 活动ID：`90001`
- 果实：`3010001`，变异ID：`28`
- 预期：两枚果实各5分，提交后总进度10，触发第一个抽奖节点

构建客户端：

```bash
docker build \
  --build-context sunnyisland=../sunnyisland \
  -f Dockerfile.client \
  -t severtest/client:local .
```

执行闭环：

```bash
mkdir -p reports
docker run --rm \
  --network master_garden_network \
  -v "$PWD/reports:/reports" \
  severtest/client:local \
  -uid 10000912 \
  -host master_garden_gate \
  -port 26002 \
  -output /reports/milestone-v2-smoke.json
```

成功时终端输出`PASSED`，详细结果位于`reports/milestone-v2-smoke.json`。

也可以使用自动化运行器，一次性完成构建、执行、报告归档和Garden日志采集：

```bash
chmod +x scripts/run_local_smoke.sh
scripts/run_local_smoke.sh
```

每次运行会生成独立目录：

```text
reports/<run-id>/
├── client.log
├── garden.log
├── metadata.json
└── milestone-v2-smoke.json
```

不同分支的Docker Compose名称可以通过环境变量覆盖：

```bash
BUILD=0 \
NETWORK=feat-wx-0120_garden_network \
GATE_HOST=feat-wx-0.12.0_garden_gate \
GARDEN_CONTAINER=feat-wx-0.12.0_garden_garden \
bash scripts/run_local_smoke.sh
```

运行器会在同一套本地Compose Redis中为测试UID写入有效期24小时的`severtest-local`登录SID，确保Gate绑定成功。可通过`PREPARE_SID=0`关闭，或用`REDIS_CONTAINER`显式指定本地Redis容器。

运行器不会删除Redis或Mongo中的Actor数据；账号重置必须单独执行并明确确认环境。

## 当前已发现问题

里程碑2.0首次初始化并提交可完整通过；但Actor释放后再次加载时，Garden日志出现`活动数据恢复异常 活动 Id 90001`，随后提交返回`操作失败`。这说明里程碑2.0的持久化/恢复链路存在缺陷，不能通过测试工具绕过，应该作为服务器问题修复并增加“提交后重启Actor再继续提交”的回归用例。

## 维护边界

- 工具不直接修改MongoDB或Redis；所有造数操作必须通过玩家Actor的请求执行。
- 本地积分仅用于规划，服务器返回值始终是最终依据。
- Adapter发现服务器积分与预测不一致时必须停止，不能继续推进玩家状态。
- 测试环境配置与协议版本必须记录在执行报告中。

## 后续测试场景

1. Actor释放并重载后继续提交，覆盖持久化恢复；
2. 节点前N分和跨节点提交；
3. 溢出10分允许、溢出11分拒绝和二次确认；
4. 每日重置、轮次切换和最终奖励；
5. 重复果实ID、非法果实和并发提交。
# Backend API

启动本地测试任务服务：

```bash
PYTHONPATH=src python3 -m severtest.server
```

启动后直接打开测试工作台：

```text
http://127.0.0.1:8088/
```

工作台包含需求文档上传、流程总览、用例及评审详情、环境配置、单个/批量执行、任务状态自动刷新和可读测试报告。前端由同一个API进程提供，不需要额外启动静态文件服务。

用例通过`module`和`feature`字段按“模块 → 功能 → 用例”组织，工作台以可折叠树状脑图展示。新增用例时应明确填写这两个字段，避免长期用例库出现未分类节点。

需求文档支持`md`、`txt`、`pdf`、`doc`和`docx`，单个文件最大20 MB，原文件保存在`requirements/`。同名文件不会覆盖，服务会自动追加上传时间。

## 需求评审工作流 API

上传需求后，响应中的`id`是后续评审任务ID：

```text
GET  /requirements/<id>
POST /requirements/<id>/events
```

后端使用受控事件驱动状态流转，不能直接修改状态。标准事件顺序：

```text
start_analysis
→ requirement_understood
→ review_completed（携带questions）
→ answers_submitted（携带answers）
→ draft_generated（携带cases）
→ supplements_submitted（携带supplements）
→ final_generated（携带cases）
→ final_approved
→ automation_generated（携带case_files）
```

执行中的阶段返回`stage_started_at`和`current_stage_duration_ms`，已结束阶段记录在`stages`中。终版用例触发`final_case_edited`后，已有自动化会标记为`outdated`，必须重新确认并生成后才能进入执行中心。

事件请求示例：

```json
{
  "event": "review_completed",
  "questions": [
    {"id": "q1", "question": "活动开始和结束条件是什么？"}
  ]
}
```

接口：

```bash
curl http://127.0.0.1:8088/health
curl http://127.0.0.1:8088/cases
curl -X POST http://127.0.0.1:8088/runs \
  -H 'Content-Type: application/json' \
  -d '{"case":"milestone-v2-submit.json","UID_VALUE":"10000000","GATE_HOST":"192.168.1.84","GATE_PORT":"27101"}'
curl http://127.0.0.1:8088/runs/<run_id>
```
