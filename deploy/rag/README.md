# 字段查询候选优化与配对验证

## 同步范围

2026-10-11 将行内已执行的查询补丁同步到开发仓库：

- `query_rewriter.py` 在显式启用时将 `F56`、`F111`、`F63.3` 等字段写法展开为 `Field 56`、`Field 111`、`Field 63.3`；在主查询改写前、改写后及英文输出中应用。
- 技术标识提取覆盖中文紧邻的完整字段与 `DE56`、`DE111` 等标识。完整子字段匹配不再重复产生父字段标识；问题单独提到父字段时仍保留它。
- 候选双语缓存使用 `bilingual:field-alias-v2:`，关闭时继续使用原来的 `bilingual:` 缓存。
- 英文检索词生成的 `max_tokens` 同步为行内已使用的 `1024`，保留现有输出清理和长度限制。
- `RAG_FIELD_ALIASES_ENABLED` 在配置类和 `.env.example` 中均默认关闭。

对齐依据是本次上传并成功执行的原安装器、子字段增量修正和行内已确认的英文查询参数。已对重建补丁结果与开发仓库查询模块进行 AST 对照（忽略注释和文档字符串）。未取得服务器全量源码快照，因此此说明不宣称整个服务器仓库逐文件一致。

安装器和一次性增量修改脚本不纳入常规部署；Git 已包含最终业务源码，避免重复打补丁。验证工具仅放在本目录，不进入线上请求流程。

## 开关与环境

```dotenv
RAG_FIELD_ALIASES_ENABLED=false
```

保持关闭时，字段规范化和新增标识提取不影响原查询流程；英文生成预算已统一为 1024。配置实例允许独立验证进程暂时切换候选规则，运行中的服务进程不会受到这种切换影响。

本次没有同步服务端 `.env`、密钥、数据库或向量库数据，也没有调整重排阈值、模型、文档产物路径或服务启动方式。行内重排阈值已观察到为 `0.5`；源码默认值仍保留已有的 `0.0`，由各环境配置管理，不能用源码默认值代替生产配置。

## 本地检查

在仓库根目录运行，以下测试使用标准库和模拟服务，不访问真实模型、数据库或向量库：

```bash
python -m unittest discover -s tests -p 'test_query_field_aliases.py' -v
python -m unittest discover -s tests -p 'test_rag_evidence_runner.py' -v
python -m unittest discover -s tests -p 'test_rag_regression_gate.py' -v
```

`tests/fixtures/query_rewriter_disabled_baseline.json` 固定了字段补丁前在可控改写/翻译桩下的 28 个查询准备结果，涵盖英文翻译成功及失败。测试不依赖 Git HEAD，提交补丁以后仍可以验证关闭流程的行为。该基线不是最终答案正确率的评估数据。

## 服务器配对检查

在实际服务仓库目录和后端 Python 环境中运行。将 `python` 替换为后端虚拟环境的 Python 路径，并选择与待复现问答相同的生成模型：

```bash
python deploy/rag/compare_field_queries.py /tmp/field-query-pairs.json
python deploy/rag/compare_rag_evidence.py \
  --out "/tmp/rag-evidence-$(date +%Y%m%d-%H%M%S)" \
  --model deepseek-v4-flash-0731-think
```

前者只验证查询准备；后者对默认 9 个新对话问题依次执行原流程和候选流程，调用真实配置的模型及检索服务，保存重排输入、API 分数、最终分块和答案。测试进程抑制 LLM 调用日志的数据库插入，主 Milvus 集合不存在时拒绝创建或重建。测试结果写入新报告目录，应用的普通日志可能同时产生；不会修改 `.env`、知识库记录或重载线上服务。

配对报告包含 `report.json` 和 `summary.md`。终端里的“F56 长度证据”只检查最终分块是否出现相应来源标识和 1537，并不自动验证长度含义，也不用于判断 F56 使用场景答案是否通过。

可以通过 `--ids` 选取案例，或用 `--cases` 指定实际完整历史：

```json
{
  "cases": [
    {
      "id": "followup_0400",
      "question": "如何修改使报文通过",
      "history": [
        {"role": "user", "content": "VISA拒绝码0400什么意思"},
        {"role": "assistant", "content": "填入当时完整的实际回答"}
      ]
    }
  ]
}
```

两侧必须使用相同完整历史、摘要、回忆、文档版本、模型及参数，不能用历史问题标题替代完整上下文。脚本默认新对话检查不能替代原始多轮复现，模型随机性也意味着单次配对无法保证未来全部问答正确。

## 发布状态与后续核验

行内截图显示已跑完 9 题配对，F56 长度证据在候选流程进入最终上下文。实际答案报告尚待对照 PDF 审核，没有宣布问答回归通过，开关仍保持关闭。

`regression_cases.json` 整理了 23 个待核验案例，包括失败问题、原来较好问题、品牌边界、子字段和标识边界。`screenshot_score` 只记录此前截图人工评分，不能作为新版本实测成绩；`regression_review_template.json` 的 before/after 均为空。

人工核验实际答案、来源引用、正确事实和证据覆盖后，另存填写好的评审文件，并执行：

```bash
python deploy/rag/check_regression_gate.py /tmp/reviewed-results.json
```

评审缺失、正确事实丢失、答案分或证据覆盖降低、候选存在严重错误时均不通过。该脚本检查已填写的评审结果，不自动从重排分推断正确率。

低分后退回原候选、纯字段精确召回、品牌来源混用、0114 表格字段合并、多轮追问漂移和条件范围误读尚未由本补丁一并解决。后续修复需要分别定位并继续做相同条件的配对验证。
