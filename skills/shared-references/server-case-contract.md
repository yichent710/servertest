# 服务器结构化用例契约

文字用例的结构化数据是唯一事实来源。页面树、评审版本和自动化代码都从该数据派生。

## 层级

```text
module（业务模块）
└── feature（业务功能）
    └── scenario（业务场景）
        └── case（具体条件、操作和预期）
```

- 沿用需求和产品中的业务命名。
- `module`、`feature`、`scenario`描述被测业务，不描述意见来源或测试方法。
- 评审问题、产品回答和测试建议通过引用关系进入已有节点。

## 用例字段

```json
{
  "id": "stable_snake_case_id",
  "name": "测试人员可读的用例名称",
  "module": "活动系统",
  "feature": "团队活动 GVE",
  "scenario": "个人积分奖励",
  "objective": "验证达到档位后只能领取一次正确奖励",
  "source_refs": ["requirement:奖励规则", "review:q3", "supplement:s2"],
  "preconditions": [],
  "steps": [],
  "expected_results": [],
  "assertions": [],
  "automation": {"status": "needs_action", "reason": "缺少团队积分查询 action"},
  "data_impact": "设置个人积分并领取奖励",
  "cleanup": "使用专用账号，不直接修改 Actor 存储",
  "server_evidence": {
    "protocols": [],
    "code_symbols": [],
    "actor_fields": [],
    "config_keys": [],
    "log_keywords": []
  },
  "change_note": "根据 q3 补充重复领奖校验"
}
```

## 约束

- `id`在迭代中保持稳定；新增业务场景才新增 ID。
- `expected_results`面向测试人员，使用业务语言描述可观察结果。
- `assertions`是终版确认后生成的机器判断，不替代文字预期。
- `source_refs`必须能追溯到需求段落、评审问题或测试建议。
- 修改前置、步骤、预期或断言语义后，自动化状态必须变为`outdated`或`needs_action`。
- 执行中心只接收终版已确认且自动化状态为`ready`的用例。
