# -*- coding: utf-8 -*-
"""查询改写器——词典匹配富集 + LLM 改写，带缓存。

改写管线（先富集、后改写）：
    1. 词典匹配富集: 三级匹配（精确/归一化/二元组重叠）在查询中找出术语,
       另做结构位置锚点探测（"数据元3的子域2" → note 指向该位置的概念
       规范名, 确定性完成, 不依赖 LLM 读表推断）, 一并渲染为结构化的
       "匹配提示";
    2. LLM 改写: 匹配提示 + 分段预算术语上下文（缩写/概念/实体三段各有
       保底配额, 防止某段独吞预算挤掉桥接知识）注入提示词, 由 LLM 综合
       产出最终检索查询（术语展开、中英互补、错别字纠正）;
    3. LLM 失败 → 返回原始查询（不做任何拼接, 不引入污染）。

关键设计: 词典匹配结果**只作为 LLM 的输入提示**, 绝不直接拼接进最终
检索查询——由 LLM 负责取舍与融合, 误匹配的术语会被丢弃而不是污染检索。
两份术语资源分工: 匹配提示是焦点信号（用户查询里实际写了什么）; 全量
术语表提供广度上下文（拼错的词匹配不到, 纠错只能靠 LLM 看全表推断）。

对改写结果做缓存，重复查询可在 1 ms 内返回。
"""

import hashlib
import json
import re
import time as _time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Union

from configure import LOGGER, PROJECT_CONFIG

# ---------------------------------------------------------------------------
# 内存存储
# ---------------------------------------------------------------------------

# 术语索引缓存：{doc_id: 已解析的索引}
_indices: Dict[str, Dict[str, Any]] = {}

# 改写缓存：{cache_key: 改写后的查询}
_cache: Dict[str, str] = {}
_cache_ttl: float = 3600.0  # 1 小时
_cache_times: Dict[str, float] = {}


@dataclass(frozen=True)
class BilingualQuery:
    """供 Dense、中文 BM25、英文 BM25 分路使用的查询。"""

    original_query: str
    primary_query: str
    english_query: str
    identifiers: Tuple[str, ...] = ()

    @property
    def rerank_query(self) -> str:
        if self.english_query and self.english_query.casefold() != self.primary_query.casefold():
            return f"{self.primary_query} | {self.english_query}"
        return self.primary_query


_bilingual_cache: Dict[str, BilingualQuery] = {}

# 中文业务口语中有少量高频术语并不总能被通用翻译模型稳定映射到卡组织
# 规范中的固定说法。这里仅补充检索同义词，不改写用户原意，也不向最终
# 回答注入事实。尤其是“追加授权”若没有 incremental authorization，英文
# BM25 会完全错过 Visa 规范中的专门章节。
_CANONICAL_ENGLISH_ALIASES: Tuple[Tuple[Tuple[str, ...], str], ...] = (
    (("追加授权", "增量授权"), "incremental authorization"),
    (("预授权",), "preauthorization"),
    (("余额查询",), "balance inquiry"),
)


# ---------------------------------------------------------------------------
# 索引加载
# ---------------------------------------------------------------------------

async def _complete_doc_ids() -> Set[str]:
    """处于 complete 状态的文档 job_id 集合（查 MySQL 文档表）。

    术语索引只为完全入库的文档服务: 术语阶段完成但后续阶段失败的文档,
    其索引文件虽已落盘, 但内容未进向量库、不可检索——若让这类文档的
    术语参与查询改写, 改写结果会引导检索去召回根本不存在的分块。
    """
    from applications.jiayueyang.services.rag_document_crud import RagDocumentCrud
    try:
        return await RagDocumentCrud().complete_doc_ids()
    except Exception as exc:
        LOGGER.warning(f"加载文档状态失败, 术语索引按空集处理: {exc}")
        return set()


async def _ensure_indices_fresh() -> None:
    """术语索引新鲜度检查: 已完成的文档索引集合变化时重新加载。

    术语索引由 Worker 进程生成落盘, Web 进程内存感知不到（跨进程内存
    不共享）——故按"已落盘索引 ∩ complete 文档"的集合变化触发重扫,
    既保证新完成文档的术语及时进入查询改写, 也保证未走完流水线的
    文档（术语就绪但后续阶段失败）不被误纳入。

    判据用集合而非数量: 只比数量时, "删一文档同时新增一个"的等量替换
    不会触发重扫, 内存里会留着已删除文档的旧索引、新文档索引缺席。
    目录列表 + 文档状态均为轻量读取, 按集合比较开销可忽略。
    """
    base = Path(PROJECT_CONFIG.RAG_OUTPUT_DIR)
    try:
        current = {
            d.name for d in base.iterdir()
            if d.is_dir() and (d / "terminology_index.json").exists()
        }
    except OSError:
        return
    current &= await _complete_doc_ids()
    if current != set(_indices):
        await load_all_indices(base)
        # 索引集合变化（新增/删除/替换文档）后必须清空改写缓存: 既有缓存是
        # 基于**旧索引集**算出的。典型故障——文档术语就绪前用户就提问, 把
        # "未改写的原始查询"缓存住（键为 query+doc_ids, TTL 1 小时）; 此后
        # 即便本函数已把新文档术语加载进 _indices, 同键缓存仍会抢先返回那条
        # 陈旧结果, 表现为"刚上传文档的术语识别不到、检索详情没有改写结果,
        # 刷新/过一会才好"。索引一变即清缓存, 保证下一次查询用最新索引改写。
        clear_rewrite_cache()


async def load_all_indices(data_dir: Optional[Union[str, Path]] = None) -> int:
    """扫描 ``RAG_OUTPUT_DIR/*/terminology_index.json`` 并加载进内存。

    仅加载状态为 complete 的文档（见 _complete_doc_ids, 查 MySQL 文档表）:
    术语阶段完成但流水线未走完的文档不参与查询改写。服务启动时调用一次,
    运行期由 _ensure_indices_fresh 按需触发。返回成功加载的索引数量。
    """
    base = Path(data_dir) if data_dir else Path(PROJECT_CONFIG.RAG_OUTPUT_DIR)
    _indices.clear()

    complete = await _complete_doc_ids()
    count = 0
    for d in sorted(base.iterdir()):
        if not d.is_dir() or d.name not in complete:
            continue
        idx_path = d / "terminology_index.json"
        if idx_path.exists():
            try:
                data = json.loads(idx_path.read_text(encoding="utf-8"))
                _indices[d.name] = data
                count += 1
            except Exception:
                LOGGER.warning(f"加载术语索引失败: {idx_path}")
    LOGGER.info(f"已加载 {count} 个术语索引")
    return count


def get_index_for_document(doc_name: str) -> Optional[Dict[str, Any]]:
    """按目录名获取单个文档的术语索引。"""
    # 先尝试精确匹配，再做模糊匹配
    if doc_name in _indices:
        return _indices[doc_name]
    # 尝试按文件名前缀匹配
    for key, idx in _indices.items():
        if idx.get("filename", "").startswith(doc_name):
            return idx
    return None


# ---------------------------------------------------------------------------
# 改写提示词
# ---------------------------------------------------------------------------

# LLM 查询改写提示词模板（业务数据，保持原文）
# 关键约束: 模型必须"只改写、不作答"——否则会把查询改写成一段带幻觉的
# 答案文本（错误术语 + 编造取值）, 反而污染检索召回
_REWRITE_PROMPT = """You are a search query rewriting engine for a technical-document knowledge base. Rewrite the user query into a better RETRIEVAL query.

You are given two terminology resources:
- "Matched Terms": terms and structural position references DETECTED in the user's query (by dictionary matching and note-anchor probing), with their canonical forms. This is the strongest signal — the rewrite should use their canonical full/Chinese/English forms.
- "Terminology Reference": the broader terminology table, useful for typo correction and additional mappings.

STRICT OUTPUT RULES (violating them breaks the search system):
- Output ONLY the rewritten query itself — a single line, at most 60 words.
- NEVER answer the query. NEVER fabricate values, lists, definitions, or explanations.
- NEVER add information that is not in the user query. The Terminology Reference serves ONLY to correct or expand terms the user actually wrote — never introduce new terms, topics, message names, or background context from it.
- No markdown, no bullet points, no brackets, no markers like **, no prefixes like "Rewritten Query:".

Rewriting rules:
1. Expand the Matched Terms into their canonical forms, e.g. the user wrote "DE3" → rewrite with its canonical name, such as "数据元3 处理码(Processing Code, DE 3)".
2. Structural position references: if Matched Terms maps a position phrase (e.g. "数据元3的子域2") to concept names, the user is asking about the concepts located at that position (the mapping comes from position notes in the terminology table) — expand the position reference into those concepts' canonical Chinese and English names, while KEEPING the position wording itself, e.g. "数据元3 处理码(Processing Code, DE 3) 子域2 持卡人"从账户"类型代码(Cardholder "From Account" Type Code)".
3. Append English terms/abbreviations after Chinese terms, e.g. "处理码(Processing Code)".
4. Correct obvious spelling mistakes and typos in technical terms / abbreviations by inferring the most likely intended term (e.g. "MAARL" → "MARL" if MARL exists; "LTSM" → "LSTM"; repeated/missing characters in acronyms). For Chinese, fix common IME errors.
5. Discard any Matched Term that is clearly unrelated to the user's actual intent.
6. Stay strictly on the user's query: never prepend or weave in background or topic context the user did not write in THIS query (e.g. a message type or subject from elsewhere).
7. Do NOT change the original intent of the query.
8. If nothing needs improvement, return the query unchanged.

Matched Terms (dictionary-matched in the user query):
{matched_terms}

Terminology Reference (broader context):
{terminology_text}

User Query: {query}

Rewritten Query (single line, no answer):"""

_ENGLISH_QUERY_PROMPT = """You are a bilingual search-query translator for technical documentation.
Translate the retrieval query below into concise English search language.

STRICT RULES:
- Output only one English query line, no explanation, markdown, label, or answer.
- Preserve every identifier, field number, acronym, API path, error code, and product name exactly.
- Do not invent facts, values, message names, or topics not present in the query.
- Prefer canonical technical terms over conversational wording.
- Maximum 60 words.

Retrieval query: {query}

English retrieval query:"""

_FIELD_ALIAS_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])F\s*(\d{1,3}(?:\.\d+)?)(?![A-Za-z0-9_./-])",
    re.IGNORECASE,
)
_FIELD_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:Field|DE)\s*\d{1,3}(?:\.\d+)?(?![A-Za-z0-9_./-])",
    re.IGNORECASE,
)


def _normalize_field_aliases(text: str) -> str:
    """展开独立的F字段缩写；兼容中文紧邻，保留路径、十六进制标签等标识。"""
    return _FIELD_ALIAS_RE.sub(lambda match: f"Field {match.group(1)}", text)


_IDENTIFIER_RE = re.compile(
    r"(?<![\w])(?:[A-Za-z]{2,}\s*-?\s*\d[A-Za-z0-9_.:/-]*|"
    r"/[A-Za-z0-9_./-]+|[A-Za-z]+_[A-Za-z0-9_]+|"
    r"[a-z]+(?:[A-Z][A-Za-z0-9]*)+)(?![\w])"
)


# ---------------------------------------------------------------------------
# 历史感知改写（指代消解）——多轮检索前把当前问题消解为自包含查询
# ---------------------------------------------------------------------------

# 注入指代消解提示词的每条历史消息字符上限: 消解只需近期问句与回答开头的
# 主题锚点, 无需整段长回答, 限制以控制提示词体积与 LLM 开销
_COREF_MSG_CHAR_LIMIT = 300

_COREF_PROMPT = """你是知识库问答系统的查询改写助手。你的唯一任务是**指代消解**: 判断用户最新提问是否在语法上依赖对话历史, 若依赖, 把依赖成分替换为历史中的具体对象, 得到一句自包含、语义完整、可直接用于知识检索的问题。

判定标准（关键: 只看语法依赖, 不看话题关联）:
1. 需要消解: 提问含代词（它/他/这个/那个/该消息）、指示承接（上一份/前者/后者/上面提到的）、缺少主语或宾语的省略句、未说明对象的追问（"为什么会失败""会怎样""呢"）。
2. 不需消解: 提问自带具体主题（字段名/消息名/编号/术语等）且句子完整——即使它紧跟上一轮话题、即使内容与上一轮相关, 也是自包含的, **必须原样返回**。话题延续不等于指代依赖。
3. 严禁把上一轮的主题、背景、消息名等任何历史内容添加、前置或合并进自包含的提问。
4. 拿不准时一律原样返回: 过度消解会向检索注入无关上下文, 比未消解危害更大。

改写约束:
- 只做"替换与补全": 用历史中的具体对象替换代词或省略成分, 不改变问法、不新增修饰、不回答问题;
- 只输出改写后的问题本身, 无解释、无前缀、无引号; 保持用户原语言。

示例 1（话题延续但自包含 → 原样返回）:
对话历史:
User: 讲讲Network Management Request/0800: Host Session Activation/Deactivation的相关内容
Assistant: 网络管理请求消息用于主机会话的激活与停用……
用户最新提问: 3域的前两位有哪些枚举值，分别指什么
改写后的问题: 3域的前两位有哪些枚举值，分别指什么

示例 2（含代词 → 消解）:
对话历史:
User: 讲讲Network Management Request/0800的相关内容
Assistant: 网络管理请求消息用于……
用户最新提问: 它包含哪些必输数据元
改写后的问题: Network Management Request/0800消息包含哪些必输数据元

对话历史:
{conversation}

用户最新提问: {query}

改写后的问题:"""

# 指代消解缓存: {key: 消解后的查询}, key = 查询 + 近期历史指纹。
# 重新生成（history 前缀与 query 均不变）时可命中, 摊销 LLM 成本
_coref_cache: Dict[str, str] = {}
_coref_cache_times: Dict[str, float] = {}
_COREF_CACHE_TTL = 3600.0
_COREF_CACHE_MAX = 512


def _coref_cache_key(query: str, history: List[Dict[str, str]]) -> str:
    fp = "|".join(f"{m.get('role', '')}:{(m.get('content') or '')[:_COREF_MSG_CHAR_LIMIT]}" for m in history)
    raw = f"{query}||{fp}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _coref_cache_get(query: str, history: List[Dict[str, str]]) -> Optional[str]:
    key = _coref_cache_key(query, history)
    if key in _coref_cache and _time.time() - _coref_cache_times.get(key, 0) < _COREF_CACHE_TTL:
        return _coref_cache[key]
    return None


def _coref_cache_set(query: str, history: List[Dict[str, str]], resolved: str) -> None:
    if len(_coref_cache) >= _COREF_CACHE_MAX:
        oldest = min(_coref_cache_times, key=_coref_cache_times.get)
        _coref_cache.pop(oldest, None)
        _coref_cache_times.pop(oldest, None)
    key = _coref_cache_key(query, history)
    _coref_cache[key] = resolved
    _coref_cache_times[key] = _time.time()


def _format_history_for_coref(history: List[Dict[str, str]]) -> str:
    """把近期历史渲染为 'User: … / Assistant: …' 文本（每条截断, 控制体积）。"""
    lines: List[str] = []
    for m in history:
        role = "User" if m.get("role") == "user" else "Assistant"
        content = (m.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content[:_COREF_MSG_CHAR_LIMIT]}")
    return "\n".join(lines) if lines else "(empty)"


async def resolve_query_with_history(
        query: str,
        history: List[Dict[str, str]],
) -> str:
    """指代消解: 结合最近几轮历史, 把当前问题消解为自包含查询（供检索）。

    仅多轮触发（history 非空）; 单轮或失败时返回原始查询（不破坏行为）。
    消解结果只用于检索, 生成回答时仍用原始问题 + 完整历史。
    """
    if not query:
        return query
    n = int(PROJECT_CONFIG.CHAT_REWRITE_HISTORY_MESSAGES or 0)
    if n <= 0 or not history:
        return query
    recent = history[-n:]

    cached = _coref_cache_get(query, recent)
    if cached is not None:
        LOGGER.debug(f"指代消解缓存命中: {query[:50]}")
        return cached

    prompt = _COREF_PROMPT.format(conversation=_format_history_for_coref(recent), query=query)
    resolved = None
    try:
        # 延迟导入: 避免模块加载期引入 LLM 客户端
        from applications.jiayueyang.rag.llm import chat_completion
        response = await chat_completion(
            messages=prompt,
            stream=False,
            max_tokens=150,
            temperature=0.0,
        )
        if isinstance(response, str) and response.strip():
            result = response.strip().splitlines()[0].strip()
            for prefix in ("Rewritten Query:", "Rewritten query:", "Resolved Query:",
                           "改写结果:", "改写:", "消解结果:"):
                if result.lower().startswith(prefix.lower()):
                    result = result[len(prefix):].strip()
            result = _clean_markers(result)
            if result and 2 <= len(result) <= 200:
                resolved = result
    except Exception as exc:
        LOGGER.warning(f"指代消解失败: {exc}——使用原始查询")

    final = resolved or query
    _coref_cache_set(query, recent, final)
    if resolved:
        LOGGER.debug(f"指代消解: 原始: {query[:50]} -> {resolved[:60]}")
    return final


# ---------------------------------------------------------------------------
# 缓存辅助函数
# ---------------------------------------------------------------------------

def _cache_key(query: str, doc_ids: FrozenSet[str]) -> str:
    raw = f"{query}|{','.join(sorted(doc_ids))}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _cache_get(query: str, doc_ids: FrozenSet[str]) -> Optional[str]:
    key = _cache_key(query, doc_ids)
    if key in _cache and _time.time() - _cache_times.get(key, 0) < _cache_ttl:
        return _cache[key]
    return None


def _cache_set(query: str, doc_ids: FrozenSet[str], rewritten: str) -> None:
    key = _cache_key(query, doc_ids)
    _cache[key] = rewritten
    _cache_times[key] = _time.time()


# ---------------------------------------------------------------------------
# 术语文本渲染（用于 LLM 提示词）——分段预算渲染
# ---------------------------------------------------------------------------

# 分段字符预算: 三类术语对改写的价值不同, 必须各自保证展示空间。
# 旧实现是"单一总预算(12000) + 顺序填充": 缩写表一项(约 11.6K)就吃光了
# 全部预算, 桥接知识最密集的概念段(约 27K)与定义锚点实体段(约 56K)对
# LLM 完全不可见——线上真实故障: 查询 "3域的前两位" 因看不到概念段里
# "持卡人交易类型代码 (DE 3子字段1)" 这条桥接记录, 改写推不出
# Subfield 1 (Cardholder Transaction Type Code), 检索整体落空。
#
# 现行分配（deepseek-chat 64K 上下文, 改写结果按查询缓存摊销成本）:
#   缩写表  12K   用户查询最常写缩写, 全量保留(含 note)
#   概念段  26K   桥接知识在 note 里, 按英文去重后全量保留
#   实体段  12K   每组至多 _ENTITY_ITEMS_PER_GROUP 条 + 总数标记
_ABBR_BUDGET = 12000
_CONCEPT_BUDGET = 26000
_ENTITY_BUDGET = 12000
# 多文档场景的最终闸门: 各文档分段渲染结果之和不得超过本值。
# 必须 ≥ 三段预算之和, 否则单文档正常渲染结果会触发退化（仅保留缩写表）
_TERM_BUDGET_TOTAL = _ABBR_BUDGET + _CONCEPT_BUDGET + _ENTITY_BUDGET
# 实体每组保留条数: 编号组通常按编号排序, 头部即最常用锚点（DE 1~6）;
# 值域枚举组（几百条代码值）对改写价值低——查具体代码时原文可被
# BM25/dense 直接命中, 无需经改写桥接
_ENTITY_ITEMS_PER_GROUP = 6


def _render_abbr_bounded(index: Dict[str, Any], budget: int) -> str:
    """缩写表渲染: 预算内按序全量保留, 超预算截断尾部条目。"""
    abbrs: List[Dict[str, str]] = index.get("abbreviations", [])
    if not abbrs:
        return ""
    lines: List[str] = ["Abbreviations:"]
    used = len(lines[0])
    for a in abbrs:
        abbr = a.get("abbr", "")
        full = a.get("full", "")
        cn = a.get("chinese", "")
        note = a.get("note", "")
        parts = [abbr, "→", full]
        if cn:
            parts.append("→")
            parts.append(cn)
        entry = "  " + " ".join(parts)
        if note:
            entry += f" ({note})"
        if used + len(entry) + 1 > budget:
            break
        lines.append(entry)
        used += len(entry) + 1
    return "\n".join(lines) if len(lines) > 1 else ""


def _render_concepts_bounded(index: Dict[str, Any], budget: int) -> str:
    """核心概念渲染: 按英文去重后预算内全量保留。

    术语抽取会为同一概念产生近义变体（"持卡人交易类型代码/码/类型"）,
    按英文（忽略大小写）去重、保留 note 最长者。note 必须原样保留——
    跨层级的桥接知识（如 "DE 3子字段1"）就写在 note 里。
    """
    by_en: Dict[str, Dict[str, str]] = {}
    for c in index.get("core_concepts", []):
        key = c.get("english", "").strip().lower()
        if not key:
            continue
        if key not in by_en or len(c.get("note", "")) > len(by_en[key].get("note", "")):
            by_en[key] = c
    if not by_en:
        return ""
    lines: List[str] = ["Core Concepts:"]
    used = len(lines[0])
    for c in by_en.values():
        cn = c.get("chinese", "")
        en = c.get("english", "")
        note = c.get("note", "")
        entry = f"  {cn} ↔ {en}"
        if note:
            entry += f" ({note})"
        if used + len(entry) + 1 > budget:
            break
        lines.append(entry)
        used += len(entry) + 1
    return "\n".join(lines) if len(lines) > 1 else ""


def _render_entities_bounded(index: Dict[str, Any], budget: int) -> str:
    """编号实体渲染: 每组保留前 N 条, 截断组附 "(…共 M 条)" 标记。"""
    groups: List[Dict[str, Any]] = index.get("entities", [])
    if not groups:
        return ""
    lines: List[str] = ["Numbered Entities:"]
    used = len(lines[0])
    for group in groups:
        cat = group.get("category", "")
        items = group.get("items", [])
        block: List[str] = [f"  [{cat}]"]
        for it in items[:_ENTITY_ITEMS_PER_GROUP]:
            eid = it.get("id", "")
            name = it.get("name", "")
            cn = it.get("chinese", "")
            note = it.get("note", "")
            entry = f"    {eid}: {name} → {cn}"
            if note:
                entry += f" ({note})"
            block.append(entry)
        if len(items) > _ENTITY_ITEMS_PER_GROUP:
            block.append(f"    (…共 {len(items)} 条)")
        block_text = "\n".join(block)
        if used + len(block_text) + 1 > budget:
            break
        lines.append(block_text)
        used += len(block_text) + 1
    return "\n".join(lines) if len(lines) > 1 else ""


# ---------------------------------------------------------------------------
# 词典匹配富集（阶段 1）——在查询中找出术语, 渲染为 LLM 提示
# ---------------------------------------------------------------------------

def _build_term_maps(
    indices: List[Dict[str, Any]],
    out: Dict[str, List[str]],
) -> None:
    """构建查找表：每个变体形式 → 规范扩展列表。"""
    for idx in indices:
        for a in idx.get("abbreviations", []):
            abbr = a.get("abbr", "")
            full = a.get("full", "")
            cn = a.get("chinese", "")
            expansions = []
            if abbr and abbr not in expansions:
                expansions.append(abbr)
            if full and full not in expansions:
                expansions.append(full)
            if cn and cn not in expansions:
                expansions.append(cn)
            for key in (abbr, full, cn):
                if key:
                    existing = out.get(key, [])
                    for e in expansions:
                        if e != key and e not in existing:
                            existing.append(e)
                    out[key] = existing

        for c in idx.get("core_concepts", []):
            cn = c.get("chinese", "")
            en = c.get("english", "")
            if cn and en:
                if cn not in out:
                    out[cn] = []
                if en not in out[cn]:
                    out[cn].append(en)
                if en not in out:
                    out[en] = []
                if cn not in out[en]:
                    out[en].append(cn)

        for group in idx.get("entities", []):
            cat = group.get("category", "")
            # 分类内嵌缩写 → 别名键: "数据元(DE)" 分类下的 id=3 条目,
            # 额外注册 "DE 3" 作为键——用户查询的自然写法就是 "DE 3",
            # 而不是索引里的完整形式 "数据元(DE) 3"
            cat_abbrs = re.findall(r"[(（]([A-Z][A-Za-z0-9 ]{0,5})[)）]", cat)
            for it in group.get("items", []):
                eid = it.get("id", "")
                name = it.get("name", "")
                cn = it.get("chinese", "")
                full_id = f"{cat} {eid}".strip() if cat else eid
                expansions = [e for e in (full_id, name, cn) if e]
                for abbr in cat_abbrs:
                    alias = f"{abbr.strip()} {eid}".strip()
                    if alias and alias not in expansions:
                        expansions.append(alias)
                for key in expansions:
                    existing = out.get(key, [])
                    for e in expansions:
                        if e != key and e not in existing:
                            existing.append(e)
                    out[key] = existing


# note 位置锚点: 术语索引的键只收录中英文名称, 位置性 note（如 "DE 3 子字段2"）
# 不进词典——"子域2" 因此永远匹配不到位于该位置的概念规范名。桥接若完全交给
# LLM 读术语表推断, 同一模式会一轮成功、一轮失败（改写 temperature=0 也救不了
# 多跳推断本身的不稳定）。此处把锚点抽取做成确定性的: 从 note 里抽出 (DE, 子字段)
# 结构, 查询侧命中相同结构时, 直接把该位置概念的规范名作为匹配提示注入。
_NOTE_ANCHOR_RE = re.compile(
    r"DE\s*(\d+)\s*(?:子元素\s*\d+\s*)?(?:子字段|子域)\s*(\d+(?:\s*/\s*\d+)*)",
    re.IGNORECASE,
)

# 查询侧结构 token: "数据元3"/"DE 3" 与 "子域2"/"子字段2" 分别捕获, 从左到右
# 扫描——不带 DE 编号的裸子域（"数据元3的子域1和子域2" 的后半截）继承查询中
# 最近一次出现的 DE 编号
_STRUCT_TOKEN_RE = re.compile(
    r"(?:(?:数据元|DE)\s*(\d+))|(?:(?:子域|子字段)\s*(\d+))",
    re.IGNORECASE,
)


def _anchor_key(de_num: str, subfield: str) -> str:
    """锚点归一化键: 消除补零与空格差异（"DE 03 子字段 2" ≡ "de3子字段2"）。"""
    return f"de{int(de_num)}子字段{int(subfield)}"


def _build_note_anchor_map(indices: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """从 note 抽取结构锚点: (DE, 子字段) → 位于该位置的术语规范形式列表。

    扫描 abbreviations/core_concepts/entities 的 note, 出现 "DE N 子字段 M"
    （兼容 "子字段2/3"、"DE 112 子元素027 子字段1"、"子字段1 值92" 等写法）
    即为该术语注册 de{N}子字段{M} 锚点。同一锚点可挂多个术语（同一子字段
    含多个概念/取值级概念）, 全部保留——提示而已, 采纳与否由 LLM 结合查询
    意图判断, 与词典匹配的定位一致。

    排序: note 恰好以子字段结尾的是"位置概念"本身（"DE 3 子字段1" →
    持卡人交易类型代码）排前; note 带 "值N" 等后缀的是该位置下的取值级
    概念（"DE 3 子字段1 值92" → PIN变更）排后——渲染只保留前几条,
    位置概念优先才不会被取值级概念挤出提示。
    """
    positional: Dict[str, List[str]] = {}
    value_level: Dict[str, List[str]] = {}
    for idx in indices:
        entries: List[Tuple[List[str], str]] = []
        for a in idx.get("abbreviations", []):
            forms = [a.get("abbr", ""), a.get("full", ""), a.get("chinese", "")]
            entries.append(([f for f in forms if f], a.get("note", "")))
        for c in idx.get("core_concepts", []):
            forms = [c.get("chinese", ""), c.get("english", "")]
            entries.append(([f for f in forms if f], c.get("note", "")))
        for group in idx.get("entities", []):
            for it in group.get("items", []):
                forms = [it.get("name", ""), it.get("chinese", "")]
                entries.append(([f for f in forms if f], it.get("note", "")))
        for forms, note in entries:
            if not forms or not note:
                continue
            for m in _NOTE_ANCHOR_RE.finditer(note):
                target = positional if not note[m.end():].strip() else value_level
                for sf in re.split(r"\s*/\s*", m.group(2)):
                    key = _anchor_key(m.group(1), sf)
                    bucket = target.setdefault(key, [])
                    for f in forms:
                        if f not in bucket:
                            bucket.append(f)
    anchors: Dict[str, List[str]] = {}
    for key in list(positional) + [k for k in value_level if k not in positional]:
        bucket: List[str] = []
        for f in positional.get(key, []) + value_level.get(key, []):
            if f not in bucket:
                bucket.append(f)
        anchors[key] = bucket
    return anchors


def _match_structural_anchors(
    query: str,
    anchors: Dict[str, List[str]],
) -> List[Tuple[str, List[str]]]:
    """结构位置探测: 查询中的 (数据元N|DE N) + (子域M|子字段M) 命中 note 锚点。

    返回 [(归一化位置表述, 该位置概念的规范形式列表), ...], 与 _match_terms
    的结果同构, 直接并入匹配提示。裸子域编号继承查询中最近的前置 DE 编号;
    无可继承则不探测——裸子域编号跨 DE 歧义（多份文档都有 "子字段2"）。
    """
    if not anchors:
        return []
    matches: List[Tuple[str, List[str]]] = []
    seen: Set[str] = set()
    last_de: Optional[str] = None
    for m in _STRUCT_TOKEN_RE.finditer(query):
        if m.group(1):
            last_de = m.group(1)
            continue
        if not last_de:
            continue
        key = _anchor_key(last_de, m.group(2))
        if key in seen or key not in anchors:
            continue
        seen.add(key)
        display = f"数据元{int(last_de)}的子域{int(m.group(2))}"
        matches.append((display, list(anchors[key])))
    return matches


def _normalize(text: str) -> str:
    """转小写，去除空格 / 标点，全角转半角。"""
    result = text.lower()
    # 全角 → 半角
    result = result.translate(
        str.maketrans(
            "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
            "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
            "０１２３４５６７８９",
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "abcdefghijklmnopqrstuvwxyz"
            "0123456789",
        )
    )
    # 去除空格、点号、连字符等
    result = re.sub(r'[\s.\-·_/]+', '', result)
    return result


def _has_bigram_overlap(term: str, query: str, threshold: float = 0.6) -> bool:
    """检查术语与查询是否共享足够多的字符二元组（覆盖率 ≥ threshold）。

    在查询上滑动窗口，围绕术语长度尝试若干窗口大小，处理**保留字符
    相邻关系**的部分匹配: 漏写尾字（"图神经网" → "图神经网络"）、
    查询带多余后缀（"图神经网络模型"）、相邻字符笔误等。

    阈值使用 0.6，避免“发起方式”误命中“发起方指示符”、以及“处理逻辑”
    误命中“处理码”这类只共享一个常见二元组的污染。能力边界（实测）:
    真缩写（"图网络" 对 "图神经网络"）相邻关系被破坏, 二元组覆盖率
    仅 0.25 < 0.6, 本级匹配不到——此类缩写要么靠
    术语索引直接收录该别名（走 L1/L2 精确/归一化匹配）, 要么靠 LLM
    基于全量术语表自行联想。不降低阈值: 低阈值会让相近但不同的术语
    （"授权请求" 对 "授权完成", 覆盖率 0.33）误命中, 污染匹配提示。

    仅对含中文的术语启用: 英文短词（"DE 113"、"DEF"）会因共享
    "DE"/"E " 两个二元组与任何含 "DE" 的查询误命中——二元组技术
    本为中文部分匹配设计。
    """
    if len(term) < 3 or len(query) < 3:
        return False
    if not re.search(r'[一-鿿]', term):
        return False
    term_bigrams = {term[i:i + 2] for i in range(len(term) - 1)}
    best = 0.0
    for start in range(len(query) - 1):
        for wsize in (len(term), len(term) + 1, len(term) + 2):
            end = start + wsize
            if end > len(query):
                continue
            window = query[start:end]
            if len(window) < 3:
                continue
            window_bigrams = {window[i:i + 2] for i in range(len(window) - 1)}
            if term_bigrams:
                overlap = len(term_bigrams & window_bigrams) / len(term_bigrams)
                if overlap > best:
                    best = overlap
    return best >= threshold


_CJK_BOUNDARY_CHARS = frozenset(
    "的是了和与及或在为对中上下内外、，。？！?：:；;（）()[]【】 \t\r\n"
)


def _contains_exact_term(term: str, query: str) -> bool:
    """精确包含检查，并阻止短中文词在另一个词内部误命中。"""
    if term not in query:
        return False
    if len(term) > 3 or not re.fullmatch(r"[\u3400-\u9fff]+", term):
        return True
    for match in re.finditer(re.escape(term), query):
        before = query[match.start() - 1] if match.start() else ""
        after = query[match.end()] if match.end() < len(query) else ""
        before_ok = not before or before in _CJK_BOUNDARY_CHARS or not re.match(r"[\u3400-\u9fff]", before)
        after_ok = not after or after in _CJK_BOUNDARY_CHARS or not re.match(r"[\u3400-\u9fff]", after)
        if before_ok and after_ok:
            return True
    return False


def _match_terms(
    query: str,
    indices: List[Dict[str, Any]],
) -> List[Tuple[str, List[str]]]:
    """词典匹配: 在查询中找出术语, 返回 [(命中表层形式, 规范扩展列表), ...]。

    三级匹配: 精确 → 归一化（大小写/空格/全半角）→ 二元组重叠（仅 ≥3 字
    中文术语）。长词优先匹配, 避免短词抢占。

    注意: 匹配结果只作为 LLM 改写的输入提示, 不直接拼接进检索查询——
    二元组级的模糊命中是否采纳, 由 LLM 结合查询意图判断。
    """
    term_map: Dict[str, List[str]] = {}
    _build_term_maps(indices, term_map)
    if not term_map:
        return []

    matches: List[Tuple[str, List[str]]] = []
    matched_keys: Set[str] = set()
    norm_query = _normalize(query)

    for term_key in sorted(term_map, key=lambda k: -len(k)):  # 长词优先
        if term_key in matched_keys:
            continue
        norm_key = _normalize(term_key)
        # 术语抽取偶尔会把代码值拆成单个字母/数字（如 ``D``、``9``）。
        # 对普通查询做子串匹配会让 ``DE39`` 同时命中这些无意义条目，污染
        # LLM 改写提示；仅当用户查询本身就是该单字符代码时才允许命中。
        if (
            len(term_key.strip()) == 1
            and re.fullmatch(r"[A-Za-z0-9]", term_key.strip())
            and norm_query != norm_key
        ):
            continue
        if _contains_exact_term(term_key, query):   # L1: 精确匹配（短中文词带边界）
            hit = True
        elif norm_key and norm_key in norm_query:   # L2: 归一化匹配
            hit = True
        elif len(term_key) >= 3 and _has_bigram_overlap(term_key, query):  # L3
            hit = True
        else:
            hit = False
        if hit:
            matches.append((term_key, term_map[term_key]))
            matched_keys.add(term_key)

    return matches


def _render_matched_terms(matches: List[Tuple[str, List[str]]]) -> str:
    """将匹配结果渲染为注入 LLM 提示词的焦点提示。"""
    if not matches:
        return "(none detected)"
    lines: List[str] = []
    for key, expansions in matches[:15]:
        # 展开列表去掉命中形式本身, 只给 LLM 看"其他规范形式"
        others = [e for e in expansions if e and e != key][:5]
        if others:
            lines.append(f'- "{key}" → {" / ".join(others)}')
        else:
            lines.append(f'- "{key}"')
    return "\n".join(lines)


def _render_mapping_hints(mapping_matches: List[Dict[str, Any]]) -> str:
    """把数据库中的确定性映射渲染成 LLM 的高优先级参考。"""
    lines: List[str] = []
    for item in mapping_matches[:10]:
        canonical = (item.get("canonical_zh") or "").strip()
        if not canonical:
            continue
        english = [item.get("official_en") or "", *(item.get("aliases_en") or [])]
        english = [str(value).strip() for value in english if str(value).strip()]
        suffix = f" / {' / '.join(english[:4])}" if english else ""
        scope = f"（适用范围：{item['scope']}）" if item.get("scope") else ""
        matched = item.get("matched_value") or canonical
        lines.append(f'- 确定映射："{matched}" → {canonical}{suffix}{scope}')
    return "\n".join(lines)


def _append_terms(query: str, terms: List[str]) -> str:
    result = query.strip()
    existing = result.casefold()
    for term in terms:
        term = (term or "").strip()
        if term and term.casefold() not in existing:
            result = f"{result} {term}".strip()
            existing = result.casefold()
    return result


def _append_deterministic_mapping_terms(
        query: str,
        mapping_matches: List[Dict[str, Any]],
) -> str:
    """保证确定性标准词进入中文主查询，避免 LLM 改写时丢失。"""
    terms: List[str] = []
    for item in mapping_matches:
        terms.append(item.get("canonical_zh") or "")
        terms.append(item.get("official_en") or "")
    return _append_terms(query, terms)


def _append_deterministic_mapping_english(
        english_query: str,
        mapping_matches: List[Dict[str, Any]],
) -> str:
    """保证官方英文词和缩写进入英文 BM25 查询。"""
    terms: List[str] = []
    for item in mapping_matches:
        terms.append(item.get("official_en") or "")
        terms.extend(item.get("aliases_en") or [])
    result = english_query.strip()
    existing = result.casefold()
    for term in terms:
        term = (term or "").strip()
        if not term:
            continue
        # “incremental auth” 是 “incremental authorization” 的前缀，
        # 但它仍是用户提供的独立 BM25 别名，不能因为子串关系被吞掉。
        pattern = rf"(?<![a-z0-9]){re.escape(term.casefold())}(?![a-z0-9])"
        if not re.search(pattern, existing):
            result = f"{result} {term}".strip()
            existing = result.casefold()
    return result


def _build_terminology_context(indices: List[Dict[str, Any]]) -> str:
    """渲染术语上下文作为 LLM 广度上下文（分段预算）。

    与匹配提示分工: 匹配提示覆盖"查询里实际写了的术语"; 术语上下文覆盖
    LLM 纠错与联想所需的其他条目（拼错的词词典匹配不到, 只有 LLM
    看到术语表才能推断 "LTSM" 应为 "LSTM"）。

    预算策略: 缩写/概念/实体三段各有独立配额（见渲染函数常量说明）,
    避免某一段独吞预算挤掉其他段。多文档场景以 _TERM_BUDGET_TOTAL 为
    最终闸门: 超限文档退化为仅缩写表, 再超限则停止纳入后续文档。
    """
    term_texts: List[str] = []
    total_chars = 0
    for idx in indices:
        abbr = _render_abbr_bounded(idx, _ABBR_BUDGET)
        concepts = _render_concepts_bounded(idx, _CONCEPT_BUDGET)
        entities = _render_entities_bounded(idx, _ENTITY_BUDGET)
        text = "\n".join(p for p in (abbr, concepts, entities) if p)
        if total_chars + len(text) > _TERM_BUDGET_TOTAL:
            text = abbr
            if not text or total_chars + len(text) > _TERM_BUDGET_TOTAL:
                break
        term_texts.append(text)
        total_chars += len(text)
    return "\n\n".join(term_texts)


# ---------------------------------------------------------------------------
# 改写主入口
# ---------------------------------------------------------------------------

async def rewrite_query(
    query: str,
    *,
    doc_ids: Optional[FrozenSet[str]] = None,
    mapping_hints: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """使用匹配文档的术语索引改写用户查询（词典富集 → LLM 改写）。

    流程：
        1. 检查改写缓存 → 命中则直接返回
        2. 加载匹配文档的术语索引（未就绪 → 返回原始查询, 不缓存）
        3. 词典匹配富集: 三级匹配找出查询中的术语 → 渲染为匹配提示
        4. LLM 改写: 匹配提示 + 全量术语表注入提示词 → 干净的检索查询
        5. LLM 失败 → 返回原始查询（不做任何拼接, 不引入污染）
    """
    doc_ids = doc_ids or frozenset()

    # 0. 索引新鲜度（Web 启动后新解析的文档需重扫才能进入改写）
    await _ensure_indices_fresh()

    # 1. 缓存检查
    mapping_hints = mapping_hints or []
    cache_query = query
    if mapping_hints:
        cache_query = f"{query}|mapping:{json.dumps(mapping_hints, ensure_ascii=False, sort_keys=True)}"
    cached = _cache_get(cache_query, doc_ids)
    if cached is not None:
        LOGGER.info(f"改写缓存命中: '{query[:60]}' -> '{cached[:200]}'")
        return cached

    # 2. 加载相关索引
    indices: List[Dict[str, Any]] = []
    if doc_ids:
        for did in doc_ids:
            idx = get_index_for_document(did)
            if idx:
                indices.append(idx)
    else:
        # 全局搜索：加载全部索引
        indices = list(_indices.values())

    if not indices:
        # 索引尚未就绪: 返回原始查询, 但不写缓存——否则索引生成后
        # 缓存仍会把"未改写"的旧结果返回整整一个 TTL 周期
        LOGGER.debug("尚未加载任何术语索引——返回原始查询（不缓存）")
        return query

    # 3. 阶段 1 — 词典匹配富集: 匹配结果只作为 LLM 的输入提示,
    #    绝不直接拼进检索查询（由 LLM 取舍融合, 误匹配不会污染搜索）
    matches = _match_terms(query, indices)
    # 结构位置锚点: "数据元3的子域2" 类位置表述在词典里命中不了概念规范名
    # （位置性 note 不是词典键）, 从 note 确定性抽锚点并在查询侧探测, 把位于
    # 该位置的概念规范名作为匹配提示前置——桥接不再依赖 LLM 读表推断
    anchor_matches = _match_structural_anchors(query, _build_note_anchor_map(indices))
    if anchor_matches:
        matches = anchor_matches + matches
    matched_terms = _render_matched_terms(matches)
    mapping_terms = _render_mapping_hints(mapping_hints)
    if mapping_terms:
        matched_terms = "\n".join(part for part in (mapping_terms, matched_terms) if part)
    # 术语改写（词典富集 + 锚点）结果打印到后台日志
    LOGGER.info(
        f"术语富集结果: query='{query[:60]}' 匹配 {len(matches)} 项"
        + (f"\n{matched_terms}" if matched_terms else "（无命中）")
    )

    # 4. 阶段 2 — LLM 改写（匹配提示 + 全量术语表一并注入）
    terminology_text = _build_terminology_context(indices)
    rewritten = None
    try:
        rewritten = await _llm_rewrite(query, matched_terms, terminology_text)
    except Exception as exc:
        LOGGER.warning(f"LLM 改写失败: {exc}——使用原始查询")

    # 5. 写入缓存并返回
    result = rewritten or query
    _cache_set(cache_query, doc_ids, result)
    # LLM 改写最终结果打印到后台日志（失败回退时也记录, 便于排查）
    if rewritten:
        LOGGER.info(f"LLM 改写结果: '{query[:60]}' -> '{result[:200]}'")
    else:
        LOGGER.info(f"LLM 改写未产出有效结果, 使用原始查询: '{query[:60]}'")
    return result


def _extract_identifiers(*texts: str, enable_field_aliases: bool = False) -> Tuple[str, ...]:
    """确定性提取技术编号、接口路径、snake_case 与 camelCase 标识。"""
    values: List[str] = []
    seen = set()
    for text in texts:
        text = _normalize_field_aliases(text or "") if enable_field_aliases else (text or "")
        matches = _IDENTIFIER_RE.finditer(text)
        if enable_field_aliases:
            fields = list(_FIELD_IDENTIFIER_RE.finditer(text))
            # 旧模式可能在中文紧邻时回退为子字段前缀，只保留完整字段匹配。
            matches = [*fields, *(m for m in matches if not any(
                f.start() <= m.start() and m.end() <= f.end() for f in fields
            ))]
        for match in matches:
            value = " ".join(match.group(0).split())
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                values.append(value)
    return tuple(values)


def _append_missing_identifiers(query: str, identifiers: Tuple[str, ...]) -> str:
    """保证 LLM 翻译未误删用户给出的精确技术标识。"""
    normalized = query.casefold()
    missing = [item for item in identifiers if item.casefold() not in normalized]
    if not missing:
        return query
    return f"{query} {' '.join(missing)}".strip()


def _append_canonical_english_aliases(source_query: str, english_query: str) -> str:
    """为明确出现的中文术语补齐规范英文同义词。"""
    additions: List[str] = []
    normalized_english = english_query.casefold()
    for source_terms, canonical in _CANONICAL_ENGLISH_ALIASES:
        if any(term in source_query for term in source_terms):
            if canonical.casefold() not in normalized_english:
                additions.append(canonical)
                normalized_english += f" {canonical.casefold()}"
    if not additions:
        return english_query
    return " ".join(part for part in (english_query.strip(), *additions) if part)


async def rewrite_query_bilingual(
    query: str,
    *,
    doc_ids: Optional[FrozenSet[str]] = None,
    mapping_matches: Optional[List[Dict[str, Any]]] = None,
    enable_field_aliases: Optional[bool] = None,
) -> BilingualQuery:
    """生成双语查询；字段别名扩展须显式启用，以便与原流程对照验证。"""
    if enable_field_aliases is None:
        enable_field_aliases = bool(getattr(PROJECT_CONFIG, "RAG_FIELD_ALIASES_ENABLED", False))
    doc_ids = doc_ids or frozenset()
    mapping_matches = mapping_matches or []
    mapping_cache_suffix = json.dumps(mapping_matches, ensure_ascii=False, sort_keys=True)
    cache_prefix = "bilingual:field-alias-v2:" if enable_field_aliases else "bilingual:"
    cache_key = _cache_key(f"{cache_prefix}{query}|mapping:{mapping_cache_suffix}", doc_ids)
    cached = _bilingual_cache.get(cache_key)
    if cached and _time.time() - _cache_times.get(cache_key, 0) < _cache_ttl:
        return cached

    primary = await rewrite_query(
        _normalize_field_aliases(query) if enable_field_aliases else query,
        doc_ids=doc_ids, mapping_hints=mapping_matches,
    )
    primary = _append_deterministic_mapping_terms(primary, mapping_matches)
    # 主查询也必须携带规范英文术语：子查询分解基于 primary，若只在独立的
    # english_query 中补词，子查询仍会沿用“追加授权(Authorization)”这一
    # 模糊说法，外层 RRF 反而把只在主查询命中的精确证据稀释掉。
    primary = _append_canonical_english_aliases(query, primary)
    if enable_field_aliases:
        primary = _normalize_field_aliases(primary)
    identifiers = _extract_identifiers(query, primary, enable_field_aliases=enable_field_aliases)
    primary = _append_missing_identifiers(primary, identifiers)

    english = ""
    try:
        english = await _llm_translate_query(primary) or ""
    except Exception as exc:
        LOGGER.warning(f"英文检索词生成失败: {exc}——保留中文与 Dense 检索")
    if english:
        if enable_field_aliases:
            english = _normalize_field_aliases(english)
        english = _append_missing_identifiers(english, identifiers)
    english = _append_canonical_english_aliases(query, english)
    english = _append_deterministic_mapping_english(english, mapping_matches)

    result = BilingualQuery(
        original_query=query,
        primary_query=primary,
        english_query=english,
        identifiers=identifiers,
    )
    _bilingual_cache[cache_key] = result
    _cache_times[cache_key] = _time.time()
    LOGGER.info(
        f"双语检索词: primary='{primary[:160]}', english='{english[:160]}', "
        f"identifiers={list(identifiers)}"
    )
    return result


# ---------------------------------------------------------------------------
# LLM 改写
# ---------------------------------------------------------------------------

async def _llm_rewrite(
    query: str,
    matched_terms: str,
    terminology_text: str,
) -> Optional[str]:
    """调用 LLM 改写查询（输入含词典匹配提示与全量术语表）。失败时返回 None。"""
    # 延迟导入：避免在模块加载阶段引入 LLM 客户端及其依赖
    from applications.jiayueyang.rag.llm import chat_completion

    prompt = _REWRITE_PROMPT.format(
        matched_terms=matched_terms,
        terminology_text=terminology_text or "(empty)",
        query=query,
    )

    # 使用较小的 max_tokens——改写后的查询应当短小
    response = await chat_completion(
        messages=prompt,
        stream=False,
        max_tokens=150,
        temperature=0.0,  # 确定性输出
    )

    if isinstance(response, str):
        # 防御"模型作答而非改写": 只取第一行, 丢弃列表/解释类输出
        result = response.strip().splitlines()[0].strip() if response.strip() else ""
        # 去掉模型可能带上的前缀
        for prefix in ("Rewritten Query:", "Rewritten query:", "改写结果:", "改写:"):
            if result.lower().startswith(prefix.lower()):
                result = result[len(prefix):].strip()
        # 清洗残留标记: 极端情况下模型会把输入格式（[ ] 括号块、** 等）
        # 原样带进输出——检索查询里不允许出现任何标记残留
        result = _clean_markers(result)
        # 合理性检查：结果不应为空; 超长说明模型仍在作答, 视为失败（调用方回退原始查询）
        if result and 2 <= len(result) <= 200:
            return result
    return None


async def _llm_translate_query(query: str) -> Optional[str]:
    """将主检索查询转换为英文关键词查询，不依赖术语索引。"""
    from applications.jiayueyang.rag.llm import chat_completion

    response = await chat_completion(
        messages=_ENGLISH_QUERY_PROMPT.format(query=query),
        stream=False,
        max_tokens=1024,
        temperature=0.0,
    )
    if not isinstance(response, str) or not response.strip():
        return None
    result = _clean_markers(response.strip().splitlines()[0].strip())
    for prefix in ("English retrieval query:", "English query:", "Translation:"):
        if result.lower().startswith(prefix.lower()):
            result = result[len(prefix):].strip()
    if 2 <= len(result) <= 300:
        return result
    return None


def _clean_markers(text: str) -> str:
    """去除 LLM 输出中残留的标记: [ ... ] 块、** 加粗符、多余空白。"""
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = text.replace("**", " ")
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# 索引缓存管理
# ---------------------------------------------------------------------------

def clear_rewrite_cache() -> None:
    """清空改写结果缓存。"""
    _cache.clear()
    _bilingual_cache.clear()
    _cache_times.clear()
