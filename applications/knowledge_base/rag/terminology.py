# -*- coding: utf-8 -*-
"""从文档 Markdown 自动生成 terminology.md。

借助 LLM 提取缩略语、核心概念以及（可选的）正式实体定义，
并给出专业的中文译名。

设计原则——质量优先于数量: 术语表服务于查询改写, 只收领域名词的
中英文对照与缩写, 宁缺毋滥。可复现性三层保障:
1. LLM 调用 temperature=0, 消除采样随机;
2. 跨批次去重带平手决胜键 + 输出按规范键排序, 消除批次完成顺序抖动;
3. 确定性规则后置过滤（中英俱在、长度/句法校验、值域枚举组丢弃）,
   LLM 输出再飘, 出口也收敛。
"""

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from configure import LOGGER, PROJECT_CONFIG


# ==================== 文档浓缩 ====================

# 表格行采样参数: 每表前 _TABLE_KEEP_FIRST 行数据全留, 此后每
# _TABLE_SAMPLE_EVERY 行留 1 行（表头、分隔行与命中编号/缩写模式
# 的行永远保留——术语定义密集的行基本都带这些模式）
_TABLE_KEEP_FIRST = 3
_TABLE_SAMPLE_EVERY = 10


def _condense_markdown(markdown: str, max_chars: int = 30000) -> str:
    """保留标题、含编号/缩写模式的行, 以及采样后的表格行。

    表格行按表采样: 表头、分隔行与命中模式的行全留, 普通数据行
    每表前 ``_TABLE_KEEP_FIRST`` 行全留、此后每 ``_TABLE_SAMPLE_EVERY``
    行留 1 行。原实现表格行无条件全留, 表格密集的大文档会把配额
    吃光, 后文的标题与定义语句被挤出摘要（摘要退化为"文档前几张
    表"）; 采样后高价值的定义行不再被重复结构行饿死。
    全局 ``max_chars`` 上限仍是最终兜底（防 OOM）。
    """
    lines = markdown.split("\n")
    kept: List[str] = []
    total = 0

    # 通用模式——不绑定任何特定领域
    id_pat = re.compile(r"\b[A-Z]{1,6}\s*\d+")  # 如 DE 2、ISO 8601、RFC 1234
    abbr_pat = re.compile(r"\b[A-Z]{2,8}\s*\([A-Za-z\s/]+\)")  # 如 PAN (Primary...)
    heading_pat = re.compile(r"^#{1,4}\s")
    table_sep_pat = re.compile(r"^\|(?:\s*:?-{2,}:?\s*\|)+\s*$")  # | --- | --- |

    in_table = False
    data_row_idx = 0  # 当前表内普通数据行计数（不含表头/分隔行）

    for line in lines:
        # 在处理任何一行之前先强制执行大小上限——防止表格密集的
        # 大文档（几乎每行都命中模式）导致 OOM。
        if total >= max_chars:
            break
        s = line.strip()
        if not s:
            in_table = False  # 空行结束表格块（Markdown 表格不跨空行）
            continue

        if s.startswith("|") and s.endswith("|"):
            if not in_table:
                in_table = True
                is_header = True  # 表格块首行视为表头
                data_row_idx = 0
            else:
                is_header = False
            if is_header or table_sep_pat.match(s):
                keep = True  # 表头/分隔行: 维持表格结构可识别
            else:
                keep = (
                    id_pat.search(s) is not None
                    or abbr_pat.search(s) is not None
                    or data_row_idx < _TABLE_KEEP_FIRST
                    or data_row_idx % _TABLE_SAMPLE_EVERY == 0
                )
                data_row_idx += 1
            if keep:
                kept.append(s)
                total += len(s) + 1
            continue

        in_table = False
        if heading_pat.match(s):
            kept.append(s)
            total += len(s) + 1
            continue
        if id_pat.search(s) or abbr_pat.search(s):
            kept.append(s)
            total += len(s) + 1
            continue

    return "\n".join(kept)


# ==================== 抽取提示词——质量优先于数量 ====================

# 术语抽取提示词模板（业务数据，保持原样）
# 范围收紧原则: 只收领域名词的中英文对照与缩写。旧版"全面完整、尽可能
# 完整列出"的导向会让 LLM 把值域枚举、通用词、描述句全灌进来, 术语表
# 臃肿且每次抽取结果漂移; 现明确"宁缺毋滥", 并由规则后置过滤兜底
_EXTRACT_PROMPT = """你是一位语言学专家，擅长技术文档的双语术语提取与翻译。

请仔细阅读以下"文档摘要"（已自动提取了标题、表格行、带编号/ID 的定义语句和缩写模式），
从中提取**领域术语的中英文对照**。术语表服务于检索改写，质量优先于数量——
宁缺毋滥：不确定就不收，宁可漏掉，也不要收入没有检索价值的条目。

输出合法 JSON。如果某类信息不存在则返回空数组 []。

## abbreviations — 缩写对照表（始终提取）

文档中真实出现的缩写、简称。
{"abbr": "缩写", "full": "英文全称", "chinese": "规范中文译名", "note": "结构锚点（规则见下）"}

格式示范（仅为说明结构，禁止将示例中的具体术语复制到输出）：
 输入片段："…通过应用程序接口 (API) 实现服务间通信与数据交换…"
 → {"abbr": "API", "full": "Application Programming Interface", "chinese": "应用程序接口", "note": ""}

## core_concepts — 名词术语对照表（始终提取）

文档中反复出现的**领域名词**，且中文和英文写法都在文档中出现过。
**只放没有对应缩写的纯概念**；已有缩写的概念只放 abbreviations，不要重复放入此表。
{"chinese": "中文术语", "english": "English term", "note": "结构锚点（规则见下）"}

格式示范（仅为说明结构，禁止将示例中的具体术语复制到输出）：
 输入片段："…the processing code (处理码) identifies the transaction type…"
 → {"chinese": "处理码", "english": "processing code", "note": "DE 3"}

## entities — 编号实体表（严格限制，大多数文档应返回 []）

仅当文档存在**条目不超过 20 个、且每个编号承载独立术语语义**的外部编号体系时才提取
（如"数据元 DE 1~6"这类少量锚点编号）。
**纯值域枚举整组跳过**：某体系下有几十上百个取值（交易类型代码表、响应码表、状态码表等），
这些取值不是术语，一个都不要列出。
章节号、图表编号、公式编号、定理编号等文档内部自引用一律不收。

JSON 结构：
[{"category": "体系名称（含前缀）", "items": [{"id": "纯编号（不含前缀）", "name": "原文名称", "chinese": "规范中文译名", "note": "结构锚点（规则见下）"}]}]

关键规则：
- category 只写文档中实际出现的前缀，不要自行推断上级标准名称，如 "数据元(DE)"
- id 只写编号本身，如 "2"（不是 "DE 2"）
- 缩写表和实体表的分工："前缀本身作为术语"（XYZ → 全称 → 中文）放 abbreviations；"带编号的具体实例"（XYZ 1、XYZ 2）放 entities

格式示范（仅为说明结构，禁止将示例中的具体术语复制到输出）：
  文档片段："…ISO 9001 质量管理体系与 ISO 14001 环境管理体系两项标准…"
  → {"category": "ISO标准", "items": [
    {"id": "9001", "name": "Quality Management Systems", "chinese": "质量管理体系", "note": ""},
    {"id": "14001", "name": "Environmental Management Systems", "chinese": "环境管理体系", "note": ""}
  ]}

# note 字段规则（所有表通用）

note 只写该术语所属的结构锚点——它隶属于哪个编号、章节或表格，
如 "DE 3 子字段1"、"§5.2 报文结构"。不超过 15 个字；不要写定义、解释或描述；
没有明确锚点就写空字符串 ""。

# 不收的内容（出现即视为错误）

- 通用词与泛称：系统、功能、数据、方法、结果、用户、模块、参数……
- 动词短语、形容词短语、完整句子
- 文档中只有中文、找不到英文对应写法的名词（core_concepts 必须中英俱在）
- 示例性内容、图表编号、章节标题本身
- 你不确定译法或含义的条目

# 规范要求

- ⚠️ 不要新增无关术语：只输出文档摘要中真实存在的内容。以上示例仅为格式说明，绝对不要出现在输出中
- ⚠️ 严格去重：每个术语只出现在一个表中
- 中文译名使用该领域专业、通用的译法
- JSON 必须合法，不要输出注释，不要用 markdown 代码块包裹

# 文档摘要

{document_summary}

# 输出格式

{"abbreviations": [{"abbr": "...", "full": "...", "chinese": "...", "note": "..."}], "core_concepts": [{"chinese": "...", "english": "...", "note": "..."}], "entities": [{"category": "...", "items": [{"id": "...", "name": "...", "chinese": "...", "note": "..."}]}]}"""


# ==================== 主入口 ====================

# 术语抽取按配置的原始 Markdown 字符数分批；生产环境可通过 .env 调整，
# 无需再次修改源码。
_BATCH_RAW_CHARS = PROJECT_CONFIG.TERMINOLOGY_BATCH_RAW_CHARS
_ARTIFACT_VERSION = 1


class TerminologyStageIncompleteError(RuntimeError):
    """术语批次未全部成功；整个术语步骤必须重试。"""


def _empty_batch_result() -> Dict[str, Any]:
    return {"abbreviations": [], "core_concepts": [], "entities": []}


def _normalise_batch_result(data: Any) -> Optional[Dict[str, Any]]:
    """校验并裁剪 LLM/检查点数据，防止损坏缓存被当成成功批次。"""
    if not isinstance(data, dict):
        return None
    result = _empty_batch_result()
    for key in result:
        value = data.get(key, [])
        if not isinstance(value, list):
            return None
        result[key] = value
    return result


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
async def generate_terminology(
    markdown: str,
    output_dir: Union[str, Path],
    *,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Optional[Path]:
    # 延迟导入：避免在模块加载阶段引入 LLM 客户端及其依赖
    from applications.knowledge_base.rag.llm import LLMTruncatedError, chat_completion

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 将大文档切分为批次
    batches = _split_into_batches(markdown, _BATCH_RAW_CHARS)
    LOGGER.info(f"术语提取: {len(batches)} 个批次")
    batch_results: Dict[int, Dict[str, Any]] = {}
    failed_batches: List[int] = []
    batch_done: List[int] = [0]    # 已完成批次数（含跳过/失败），进度单调递增

    semaphore = asyncio.Semaphore(PROJECT_CONFIG.TERMINOLOGY_BATCH_CONCURRENCY)

    async def _process_batch(bi: int, batch_md: str) -> None:
        try:
            extracted = await _extract_batch(bi, batch_md, depth=0)
            if extracted is None:
                failed_batches.append(bi)
                return
            batch_results[bi] = extracted
        finally:
            # 批次并发执行, 完成顺序与编号不一致: 上报"已完成数"而非
            # 批次编号（原实现上报 bi+1, 进度条会往回走）; 跳过/失败
            # 的批次同样计数, 避免进度永远停在 100% 以下。
            # 计数只在最外层做一次: 截断重切派生的子批次归入父批次,
            # 保证 done 不超过分母 len(batches)、进度单调收敛到 100%
            batch_done[0] += 1
            if progress_callback:
                try:
                    progress_callback(batch_done[0], len(batches))
                except Exception as exc:
                    # 进度写回失败不影响术语提取本身, 但不能无声吞掉:
                    # 存储异常时进度会静默停滞, 需要日志可供排查
                    LOGGER.warning(
                        f"批次 {bi + 1}/{len(batches)} 进度回调失败: "
                        f"{type(exc).__name__}: {exc}"
                    )

    # 截断重切的递归深度上限与最小可切字符数: 无标题的扁平批次无法按
    # 边界细分, 兜底直接放弃并明确记日志（而非无声丢术语或无限递归）
    _MAX_TRUNCATION_DEPTH = 3
    _MIN_RESLIT_CHARS = 8000

    async def _extract_batch(
        bi: int,
        batch_md: str,
        depth: int,
    ) -> Optional[Dict[str, Any]]:
        """单批抽取: 浓缩 → LLM 调用 → JSON 解析 → 返回本批结果。

        输出截断（finish_reason=length）时先释放信号量槽位, 再把批次对半
        重切后递归重试——重切在 ``async with semaphore`` 之外进行, 避免
        父任务持槽等待需槽位的子任务造成死锁。子批次不单独计进度。
        """
        truncated = False
        async with semaphore:
            condensed = _condense_markdown(batch_md)
            if len(condensed) < 200:
                LOGGER.info(f"批次 {bi + 1}/{len(batches)} 跳过：摘要过短")
                return _empty_batch_result()

            prompt = _EXTRACT_PROMPT.replace("{document_summary}", condensed)

            try:
                response = await chat_completion(
                    messages=prompt,
                    stream=False,
                    response_format={"type": "json_object"},
                    max_tokens=PROJECT_CONFIG.TERMINOLOGY_MAX_TOKENS,
                    # 术语表必须对同一文档可复现: 不传时继承全局温度
                    # （问答用 0.7）, 抽取结果会逐次漂移——显式锁 0
                    temperature=0.0,
                )
                if isinstance(response, str):
                    raw = response
                else:
                    token_chunks: List[str] = []
                    async for token in response:
                        token_chunks.append(token)
                    raw = "".join(token_chunks)
            except LLMTruncatedError:
                # 截断不是终局失败: 出槽后对半重切重试（见下方）
                truncated = True
            except Exception as exc:
                LOGGER.warning(f"批次 {bi + 1}/{len(batches)} LLM 失败: {exc}")
                return None

            if not truncated:
                extracted = _parse_json_response(raw)
                extracted = _normalise_batch_result(extracted)
                if extracted is None:
                    LOGGER.warning(f"批次 {bi + 1}/{len(batches)} JSON 解析失败")
                    return None

        if not truncated:
            return extracted

        # ---- 截断重试: 信号量槽位已释放, 子批次各自独立抢槽, 无死锁 ----
        if depth >= _MAX_TRUNCATION_DEPTH or len(batch_md) < _MIN_RESLIT_CHARS:
            LOGGER.error(
                f"批次 {bi + 1}/{len(batches)} LLM 输出截断（max_tokens="
                f"{PROJECT_CONFIG.TERMINOLOGY_MAX_TOKENS}）且无法继续细分, 放弃: "
                f"该批术语全部缺失"
            )
            return None
        halves = _split_into_batches(batch_md, max(len(batch_md) // 2, 1))
        if len(halves) < 2:
            LOGGER.error(
                f"批次 {bi + 1}/{len(batches)} LLM 输出截断且无标题边界可切分, "
                f"放弃: 该批术语全部缺失"
            )
            return None
        LOGGER.warning(
            f"批次 {bi + 1}/{len(batches)} LLM 输出截断（max_tokens="
            f"{PROJECT_CONFIG.TERMINOLOGY_MAX_TOKENS}）, 重切为 {len(halves)} 个子批次重试"
        )
        child_results = await asyncio.gather(*[
            _extract_batch(bi, half, depth + 1) for half in halves
        ])
        if any(result is None for result in child_results):
            return None
        combined = _empty_batch_result()
        for result in child_results:
            assert result is not None
            for key in combined:
                combined[key].extend(result[key])
        return combined

    await asyncio.gather(*[
        _process_batch(i, batch_md) for i, batch_md in enumerate(batches)
    ])

    if failed_batches:
        failed_text = ", ".join(str(index + 1) for index in sorted(failed_batches))
        raise TerminologyStageIncompleteError(
            f"术语提取未完成：{len(failed_batches)}/{len(batches)} 个批次失败 "
            f"(批次 {failed_text})；本步骤未生成完成产物，重试时将重新执行整个术语步骤"
        )

    all_abbrs: List[Dict[str, str]] = []
    all_concepts: List[Dict[str, str]] = []
    all_entities: List[Dict[str, Any]] = []
    for bi in range(len(batches)):
        result = batch_results[bi]
        all_abbrs.extend(result["abbreviations"])
        all_concepts.extend(result["core_concepts"])
        all_entities.extend(result["entities"])

    # 跨批次合并与去重
    merged = _merge_batch_results(all_abbrs, all_concepts, all_entities)
    if not merged:
        LOGGER.info("术语表跳过：合并后无数据")
        merged = _empty_batch_result()

    md_content = _format_terminology_md(merged)
    if not md_content:
        md_content = "# 术语对应表\n\n> 未从文档中提取到符合规则的术语。\n"

    # 产物写盘移交线程池: 不在事件循环上做同步文件 IO,
    # 与管道其他阶段（PDF/字节流落盘）的 to_thread 风格一致
    output_path = output_dir / "terminology.md"
    await asyncio.to_thread(_atomic_write_text, output_path, md_content)
    LOGGER.info(
        f"术语表已生成: {output_path} "
        f"({len(merged.get('abbreviations', []))} 缩写, "
        f"{len(merged.get('core_concepts', []))} 概念, "
        f"{len(merged.get('entities', []))} 实体组)"
    )

    # 同时写出机器可读索引，供查询改写使用
    index_path = output_dir / "terminology_index.json"
    index_data = dict(merged)
    index_data["filename"] = output_dir.name
    index_data["stage_meta"] = {
        "version": _ARTIFACT_VERSION,
        "source_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        "llm_model": getattr(PROJECT_CONFIG, "LLM_MODEL", ""),
        "max_tokens": PROJECT_CONFIG.TERMINOLOGY_MAX_TOKENS,
    }
    index_payload = json.dumps(index_data, ensure_ascii=False, indent=2)
    await asyncio.to_thread(_atomic_write_text, index_path, index_payload)
    # 不在此处注册进查询改写内存: 术语阶段完成时文档尚未 complete,
    # 其索引不应参与查询改写; Web 进程按"索引落盘 ∩ complete 文档"
    # 的集合变化自行重扫加载（见 query_rewriter._ensure_indices_fresh）
    LOGGER.info(f"术语索引已生成: {index_path}")

    return output_path


# ==================== 批次切分——在标题边界处切分 ====================

def _split_into_batches(markdown: str, batch_chars: int) -> List[str]:
    """将 Markdown 按结构边界切分为批次（多级边界级联降级）。

    每批约为 ``batch_chars`` 个原始 Markdown 字符（浓缩前）。边界优先级:
    ``## `` 二级标题 → 任意级标题 → 段落（空行）→ 行边界。

    原实现仅识别 ``## `` 边界, 无标题结构的文档（OCR 扁平产物常见）
    整篇成为单批, 浓缩后只剩前 3 万字、后文术语全部丢失; 级联降级
    保证任何文档都会被切到批次上限以内。单个超长结构单元（章节/
    段落）独立成批——绝不在结构单元中间切开; 唯有全篇无任何分隔符
    的极端文本才硬切兜底。
    """
    if len(markdown) <= batch_chars:
        return [markdown]

    # 级联降级: 优先粗粒度边界（批次少、LLM 调用少）, 逐级细化
    for pattern in (r"\n(?=## )", r"\n(?=#{1,6} )", r"\n(?=[ \t]*\n)"):
        sections = re.split(pattern, markdown)
        if len(sections) > 1:
            return _pack_sections(sections, batch_chars)

    # 无标题也无空行: 退到单行边界（保留行的完整性）
    lines = markdown.split("\n")
    if len(lines) > 1:
        return _pack_sections(lines, batch_chars)

    # 极端: 整篇无换行, 硬切兜底
    return [markdown[i:i + batch_chars] for i in range(0, len(markdown), batch_chars)]


def _pack_sections(sections: List[str], batch_chars: int) -> List[str]:
    """贪心装箱: 将结构单元按原文顺序打包为 ≤ ``batch_chars`` 的批次。

    单个超长单元独立成批（不切断结构单元本身）。
    """
    batches: List[str] = []
    current: List[str] = []
    current_len = 0

    for sec in sections:
        if current_len + len(sec) > batch_chars and current:
            batches.append("\n".join(current))
            current = []
            current_len = 0
        current.append(sec)
        current_len += len(sec)

    if current:
        batches.append("\n".join(current))

    return batches


# ==================== 确定性后置过滤——LLM 输出可飘, 出口必须收敛 ====================

# 字段长度上限: 术语应当是简短词组, 超限视为描述句/整段复制, 直接丢弃
_ABBR_MAX_LEN = 12      # 缩写本身
_FULL_MAX_LEN = 80      # 英文全称
_ZH_TERM_MAX_LEN = 30   # 中文术语
_EN_TERM_MAX_LEN = 60   # 英文术语
# note 提示词要求 ≤15 字锚点, 过滤放宽到 20 字截断保留——锚点略长
# 不该连累整个条目被丢（截断而非丢弃, 与长度超限的"整条丢弃"区分开）
_NOTE_MAX_LEN = 20

# 句法标点: 术语/锚点里不应出现, 命中说明 LLM 写的是描述句而非词组
_SENTENCE_PUNCT = "。，、；！？!?…"


def _has_sentence_punct(text: str) -> bool:
    return any(ch in _SENTENCE_PUNCT for ch in text)


def _trim_note(note: Any) -> str:
    note = str(note or "").strip()
    return note[:_NOTE_MAX_LEN] if len(note) > _NOTE_MAX_LEN else note


def _filter_abbreviations(abbrs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """缩写条目过滤: abbr 与中文必须俱在（中英对照表）, 拒收句子型条目。"""
    kept: List[Dict[str, str]] = []
    for a in abbrs:
        if not isinstance(a, dict):
            continue
        abbr = str(a.get("abbr") or "").strip()
        full = str(a.get("full") or "").strip()
        chinese = str(a.get("chinese") or "").strip()
        if not abbr or not chinese:
            continue
        if len(abbr) > _ABBR_MAX_LEN or len(chinese) > _ZH_TERM_MAX_LEN or len(full) > _FULL_MAX_LEN:
            continue
        if _has_sentence_punct(abbr) or _has_sentence_punct(full) or _has_sentence_punct(chinese):
            continue
        kept.append({"abbr": abbr, "full": full, "chinese": chinese, "note": _trim_note(a.get("note"))})
    return kept


def _filter_concepts(concepts: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """概念条目过滤: 中英文必须俱在（对照表不收单语条目）, 拒收句子型条目。"""
    kept: List[Dict[str, str]] = []
    for c in concepts:
        if not isinstance(c, dict):
            continue
        chinese = str(c.get("chinese") or "").strip()
        english = str(c.get("english") or "").strip()
        if not chinese or not english:
            continue
        if len(chinese) > _ZH_TERM_MAX_LEN or len(english) > _EN_TERM_MAX_LEN:
            continue
        if _has_sentence_punct(chinese) or _has_sentence_punct(english):
            continue
        kept.append({"chinese": chinese, "english": english, "note": _trim_note(c.get("note"))})
    return kept


def _filter_entity_groups(groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """只保留少量条目的锚点组: 条目数超阈值的组判定为纯值域枚举（代码值表）, 整组丢弃。

    必须在跨批次合并**之后**调用——单批看到的条目数只是局部, 合并后的
    总数才是该编号体系的真实规模。
    """
    kept: List[Dict[str, Any]] = []
    for g in groups:
        if not isinstance(g, dict):
            continue
        items = [it for it in g.get("items", []) if isinstance(it, dict) and str(it.get("id") or "").strip()]
        if not items:
            continue
        if len(items) > PROJECT_CONFIG.TERMINOLOGY_ENTITY_MAX_ITEMS:
            LOGGER.debug(
                f"实体组丢弃: {g.get('category', '')}（{len(items)} 条, "
                f"超过上限 {PROJECT_CONFIG.TERMINOLOGY_ENTITY_MAX_ITEMS}, 判定为值域枚举）"
            )
            continue
        cleaned: List[Dict[str, str]] = []
        for it in items:
            name = str(it.get("name") or "").strip()
            chinese = str(it.get("chinese") or "").strip()
            if not name and not chinese:
                continue
            cleaned.append({
                "id": str(it.get("id") or "").strip(),
                "name": name,
                "chinese": chinese,
                "note": _trim_note(it.get("note")),
            })
        if cleaned:
            kept.append({"category": str(g.get("category") or "").strip(), "items": cleaned})
    return kept


# ==================== 批次合并——跨批次去重 ====================

def _merge_batch_results(
    all_abbrs: List[Dict[str, str]],
    all_concepts: List[Dict[str, str]],
    all_entities: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """合并多个批次的结果并去重（同键择优保留, 输出按规范键排序）。

    各表先过确定性过滤（中英俱在、长度/句法校验）再去重; 实体组合并后
    按条目数过滤值域枚举。排序输出保证产物与批次完成顺序无关、可复现。
    """

    # 缩略语按 abbr 去重: 跨批次对同一缩写给出的 full/note 质量不一
    # （首次出现未必最佳, 后文批次可能有更完整的上下文）, 故同键
    # 择优保留, 而非简单的首次出现胜出
    abbrs = _dedupe_by_best(
        _filter_abbreviations(all_abbrs),
        key_fn=lambda a: (a.get("abbr") or "").strip().upper(),
        fields=("full", "chinese", "note"),
        key_field="abbr",  # 大小写归一写回展示字段
    )
    abbrs.sort(key=lambda a: (a.get("abbr") or "").upper())

    # core_concepts 按 chinese 去重（同样择优保留, 并写回去空白后的规范键）
    concepts = _dedupe_by_best(
        _filter_concepts(all_concepts),
        key_fn=lambda c: (c.get("chinese") or "").strip(),
        fields=("english", "note"),
        key_field="chinese",
    )
    concepts.sort(key=lambda c: c.get("chinese") or "")

    # 跨批次归一化 category 名称
    # 不同批次可能给同一编号体系起不同的名字
    # （如 "消息类型"、"消息类型(MTI)"、"消息类型码(MTI)"）。
    # 提取括号内的缩写作为规范键，取最长名称作为规范形式，
    # 再按规范键合并。
    _cat_forms: Dict[str, List[str]] = {}  # 规范键 → [category 名称列表]
    _cat_items: Dict[str, Dict[str, Dict[str, str]]] = {}  # 规范键 → {id → 条目}
    _canonical_name: Dict[str, str] = {}  # 规范键 → 最佳展示名称

    for group in all_entities:
        cat = group.get("category", "").strip()
        if not cat:
            continue
        ckey = _canonical_category_key(cat)

        # 记录该 category 名称的全部写法
        if ckey not in _cat_forms:
            _cat_forms[ckey] = []
        if cat not in _cat_forms[ckey]:
            _cat_forms[ckey].append(cat)

        # 取最长名称作为规范形式（描述最完整）
        if ckey not in _canonical_name or len(cat) > len(_canonical_name[ckey]):
            _canonical_name[ckey] = cat

        # 合并条目
        if ckey not in _cat_items:
            _cat_items[ckey] = {}
        for it in group.get("items", []):
            eid = it.get("id", "").strip()
            if eid and eid not in _cat_items[ckey]:
                _cat_items[ckey][eid] = it

    entities: List[Dict[str, Any]] = []
    for ckey in sorted(_cat_items):
        items = list(_cat_items[ckey].values())
        items.sort(key=lambda x: _sort_key(x.get("id", "")))
        entities.append({"category": _canonical_name.get(ckey, ckey), "items": items})

    # 合并后再过滤: 单批看到的条目数只是局部, 合并总数才能判定值域枚举
    entities = _filter_entity_groups(entities)

    if not abbrs and not concepts and not entities:
        return None

    return {
        "abbreviations": abbrs,
        "core_concepts": concepts,
        "entities": entities,
    }


def _dedupe_by_best(
    entries: List[Dict[str, str]],
    *,
    key_fn: Callable[[Dict[str, str]], str],
    fields: tuple,
    key_field: Optional[str] = None,
) -> List[Dict[str, str]]:
    """按 ``key_fn`` 归一去重, 同键保留 ``fields`` 总长度最大（最完整）者。

    完整度打平时按条目的 JSON 序列化字典序决胜——原实现平手时"先见者
    胜", 而先见序取决于批次并发完成顺序, 同一文档两次抽取会选出不同
    条目; 字典序与到达顺序无关, 保证择优结果可复现。
    空键条目直接丢弃。``key_field`` 给出时, 将归一化后的键写回该展示
    字段——例如 abbr 在各批次中可能写作 "mti"/"Mti"/"MTI", 归一键为大写,
    写回后术语表统一展示规范大小写（择优保留的条目原始大小写不定）。
    """
    best: Dict[str, Dict[str, str]] = {}
    for entry in entries:
        key = key_fn(entry)
        if not key:
            continue
        if key not in best:
            best[key] = entry
            continue
        new_score = _entry_completeness(entry, fields)
        old_score = _entry_completeness(best[key], fields)
        if new_score > old_score or (
            new_score == old_score
            and json.dumps(entry, ensure_ascii=False, sort_keys=True)
            < json.dumps(best[key], ensure_ascii=False, sort_keys=True)
        ):
            best[key] = entry
    if key_field:
        return [{**best[k], key_field: k} for k in best]
    return list(best.values())


def _entry_completeness(entry: Dict[str, str], fields: tuple) -> int:
    """条目完整度评分: 参与字段的内容总长度, 用于同键去重时择优。"""
    return sum(len(str(entry.get(f) or "")) for f in fields)


def _canonical_category_key(cat: str) -> str:
    """将 category 名称归一化为规范键，用于跨批次合并。

    "数据元(DE)" 与 "DE" 都映射到键 "DE"；
    "消息类型(MTI)" 与 "消息类型码(MTI)" 都映射到 "MTI"。
    """
    # 提取括号内的缩写作为规范键
    m = re.search(r"\(([^)]+)\)", cat)
    if m:
        return m.group(1).upper()
    # 短的全大写名称直接原样使用
    if cat.isascii() and cat == cat.upper() and len(cat) <= 8:
        return cat.upper()
    # 兜底：使用完整名称
    return cat.strip()


def _sort_key(raw_id: str):
    """按自然序排列实体 ID：'2' < '10' < '110'。"""
    try:
        return (0, int(raw_id))
    except ValueError:
        return (1, raw_id)


# ==================== JSON 解析 ====================

def _parse_json_response(raw: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        try:
            return json.loads(m.group(1))  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            return json.loads(m.group(0))  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass
    return None


# ==================== Markdown 排版——自适应表格 ====================

def _format_terminology_md(data: Dict[str, Any]) -> Optional[str]:
    parts: List[str] = [
        "# 术语对应表",
        "",
        "> 本文档由 LLM 自动生成，基于文档内容提取术语映射。用于查询改写，提高向量检索命中率。",
        "",
    ]

    # 1. 编号实体表（仅技术规范类文档有）
    # 新格式：entity_groups，每个 category 一张子表
    entity_groups: List[Dict[str, Any]] = data.get("entities", [])
    if entity_groups:
        # 检测旧的扁平格式并转换，保持向后兼容
        # 按全量分组判断（而非只看首组），混合格式一律按新格式渲染
        if all("category" not in g and "items" not in g for g in entity_groups):
            # 旧格式：[{"id": "...", "name": "...", ...}] —— 视为单一未分组表格
            parts.append("## 编号实体表")
            parts.append("")
            parts.append("| 编号 | 原文名称 | 中文名 | 锚点 |")
            parts.append("| --- | --- | --- | --- |")
            for e in entity_groups:
                parts.append(
                    f"| {e.get('id', '')} | {e.get('name', '')} | {e.get('chinese', '')} | {e.get('note', '')} |"
                )
            parts.append("")
        else:
            for group in entity_groups:
                cat = group.get("category", "编号实体")
                items: List[Dict[str, str]] = group.get("items", [])
                if not items:
                    continue
                parts.append(f"## {cat}")
                parts.append("")
                parts.append("| 编号 | 原文名称 | 中文名 | 锚点 |")
                parts.append("| --- | --- | --- | --- |")
                for it in items:
                    parts.append(
                        f"| {it.get('id', '')} | {it.get('name', '')} | {it.get('chinese', '')} | {it.get('note', '')} |"
                    )
                parts.append("")

    # 2. 缩略语对照表（所有文档类型）
    abbrs: List[Dict[str, str]] = data.get("abbreviations", [])
    if abbrs:
        parts.append("## 缩略语对照表")
        parts.append("")
        parts.append("| 缩写 | 英文全称 | 中文 | 锚点 |")
        parts.append("| --- | --- | --- | --- |")
        for a in abbrs:
            parts.append(
                f"| {a.get('abbr', '')} | {a.get('full', '')} | {a.get('chinese', '')} | {a.get('note', '')} |"
            )
        parts.append("")

    # 3. 核心概念术语表（所有文档类型）
    core: List[Dict[str, str]] = data.get("core_concepts", [])
    if core:
        parts.append("## 核心概念术语表")
        parts.append("")
        parts.append("| 中文 | 英文 | 锚点 |")
        parts.append("| --- | --- | --- |")
        for t in core:
            parts.append(f"| {t.get('chinese', '')} | {t.get('english', '')} | {t.get('note', '')} |")
        parts.append("")

    # 至少需要一张数据表（标题 + 说明之外的内容）
    if len(parts) <= 4:
        return None
    return "\n".join(parts)
