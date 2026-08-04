# severtest

SunnyIsland服务器先行测试工具。第一阶段用于生成“活动里程碑2.0”测试前置条件计划，后续通过Adapter接入现有Garden测试客户端协议。

## 当前能力

- 加载并校验里程碑活动配置；
- 按服务器规则计算果实积分；
- 计算到指定积分所需的最少果实组合；
- 生成稳定、可审计的JSON计划；
- 在输出中记录配置SHA-256，避免使用错误版本的配置；
- 提供结构化JSON日志；
- 通过`ServerAdapter`隔离业务规划和SunnyIsland私有协议。

当前示例配置只用于验证工具流程，不代表线上数值。接入测试服前必须替换为对应环境的真实活动、果实和变异配置。

## 运行

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

## 维护边界

- 工具不直接修改MongoDB或Redis；所有造数操作必须通过玩家Actor的请求执行。
- 本地积分仅用于规划，服务器返回值始终是最终依据。
- Adapter发现服务器积分与预测不一致时必须停止，不能继续推进玩家状态。
- 测试环境配置与协议版本必须记录在执行报告中。

## 下一步

1. 从SunnyIsland的`cmd/garden-client/internal/clientx`提取独立协议Adapter；
2. 接入`DebugGiveHarvestReq`和`SubmitMilestoneV2FruitsReq`；
3. 使用测试服真实配置替换示例目录；
4. 实现“节点前N分”和“溢出11分”两个首批条件模板；
5. 保存服务器响应、背包ID和最终人工测试指引。
