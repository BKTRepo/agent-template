"""Preserve source heading ownership without inferring it from body keywords."""

import bisect
import json
import re
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any, Dict, List

SECTION_METADATA_KEYS = (
    "section_path", "section_title", "section_field_no", "section_status",
    "section_segments", "section_source", "section_context_version",
)
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_FIELD = re.compile(r"^(?:Field|DE|F)\s*(\d+(?:\.\d+)*)(?=\s|[,，–—:-]|$)", re.I)
_MAJOR = re.compile(r"^(?:Chapter\b|Appendix\b|第.{1,12}章|附录)", re.I)


def restore_pdf_heading_hierarchy(markdown: str, docling_json_path, pdf_path) -> str:
    """Restore flattened headings only when source PDF typography proves a hierarchy.

    Match Docling section headers to source-page spans by text and position. Body
    keywords never determine ownership. Missing/ambiguous layout leaves Markdown
    unchanged; unrelated peer headings retain their own typographic level.
    """
    lines = markdown.splitlines(keepends=True)
    headings = []
    fenced = False
    for index, line in enumerate(lines):
        if re.match(r"^\s*(`{3,}|~{3,})", line):
            fenced = not fenced
        match = None if fenced else _HEADING.match(line.rstrip("\r\n"))
        if match:
            headings.append((index, len(match.group(1)), match.group(2)))
    # Explicit Markdown nesting already provides stronger evidence than typography.
    if not headings or len({level for _, level, _ in headings}) != 1:
        return markdown
    if not pdf_path or not Path(pdf_path).is_file() or not Path(docling_json_path).is_file():
        return markdown
    normalize = lambda text: re.sub(r"\s+", " ", text).strip().casefold()
    try:
        import fitz
        raw = json.loads(Path(docling_json_path).read_text(encoding="utf-8"))
        headers = [t for t in raw.get("texts", []) if t.get("label") == "section_header"]
        by_title = {}
        page_spans = {}
        with fitz.open(pdf_path) as pdf:
            for header in headers:
                measurements = []
                title = normalize(header.get("text", ""))
                for provenance in header.get("prov", []):
                    page_no = int(provenance.get("page_no", 0)) - 1
                    bbox = provenance.get("bbox", {})
                    if not 0 <= page_no < len(pdf) or not all(k in bbox for k in ("l", "r", "t", "b")):
                        continue
                    page = pdf[page_no]
                    if bbox.get("coord_origin", "BOTTOMLEFT") == "BOTTOMLEFT":
                        top, bottom = page.rect.height - bbox["t"], page.rect.height - bbox["b"]
                    else:
                        top, bottom = bbox["t"], bbox["b"]
                    area = fitz.Rect(bbox["l"] - 4, min(top, bottom) - 4,
                                     bbox["r"] + 4, max(top, bottom) + 4)
                    if page_no not in page_spans:
                        page_spans[page_no] = [s for block in page.get_text("dict")["blocks"]
                            for line in block.get("lines", []) for s in line.get("spans", [])]
                    for span in page_spans[page_no]:
                        value = normalize(span.get("text", ""))
                        if value and value in title and fitz.Rect(span["bbox"]).intersects(area):
                            measurements.extend([float(span["size"])] * min(len(value), 100))
                if measurements:
                    by_title.setdefault(title, []).append(median(measurements))
        # A repeated title with incompatible typography is ambiguous, not guessed.
        sizes = {title: median(values) for title, values in by_title.items()
                 if max(values) - min(values) <= max(0.75, median(values) * 0.05)}
        matched = [sizes.get(normalize(title)) for _, _, title in headings]
        # Partial reconstruction could leak an old field into an unrelated heading.
        if any(size is None for size in matched):
            return markdown
        tiers = []
        for size in sorted(matched, reverse=True):
            if not tiers or tiers[-1] / size >= 1.15:
                tiers.append(size)
        if len(tiers) < 2 or len(tiers) > 6:
            return markdown
        base = min(level for _, level, _ in headings)
        for (index, _, title), size in zip(headings, matched):
            tier = min(range(len(tiers)), key=lambda i: abs(tiers[i] - size))
            level = min(6, base + tier)
            ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
            lines[index] = "#" * level + " " + title + ending
        return "".join(lines)
    except (OSError, ValueError, KeyError, TypeError, ImportError, AttributeError, RuntimeError):
        return markdown


def markdown_sections(text: str) -> List[Dict[str, Any]]:
    """Return source-offset sections; code fences and recurring page banners are not headings."""
    headings = []
    offset = 0
    fence = ""
    previous = None
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            token = marker.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            previous = None
        elif not fence:
            match = _HEADING.match(line.rstrip("\r\n"))
            if match:
                headings.append((offset, len(match.group(1)), match.group(2).strip()))
                previous = None
            elif previous and re.fullmatch(r" {0,3}(?:={3,}|-{3,})\s*", line.rstrip("\r\n")):
                headings.append((previous[0], 1 if stripped.startswith("=") else 2, previous[1]))
                previous = None
            else:
                previous = (offset, stripped) if stripped else None
        offset += len(line)
    counts = Counter(title for _, _, title in headings)
    # Long document titles repeatedly printed in page headers do not end a field section.
    banners = {title for title, n in counts.items() if n >= 10 and len(title) >= 60 and not _FIELD.match(title)}
    sections = []
    stack = []
    start = 0
    for position, level, title in headings:
        if title in banners:
            continue
        if position > start:
            sections.append(_section(start, position, stack))
        # Docling often emits field subsections (e.g. "MIT:") at the same
        # Markdown level as their containing field. A colon label is a local
        # subsection, not a new field. Ordinary peer headings still end scope.
        if title.endswith(":") and not _MAJOR.match(title) and stack and _FIELD.match(stack[-1][1]) and level == stack[-1][0]:
            level += 1
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        start = position
    if start < len(text):
        sections.append(_section(start, len(text), stack))
    return sections


def _section(start, end, stack):
    path = [title for _, title in stack]
    field = ""
    for title in reversed(path):
        match = _FIELD.match(title)
        if match:
            field = match.group(1)
            break
    return {"start": start, "end": end, "section_path": path,
            "section_title": path[-1] if path else "", "section_field_no": field}


def _metadata(sections, starts, start, end):
    first = max(0, bisect.bisect_right(starts, start) - 1)
    parts = []
    for section in sections[first:]:
        if section["start"] >= end:
            break
        left, right = max(start, section["start"]), min(end, section["end"])
        if right > left:
            parts.append({"start": left - start, "end": right - start,
                          **{k: section[k] for k in ("section_path", "section_title", "section_field_no")}})
    identities = {tuple(p["section_path"]) for p in parts}
    status = "mixed" if len(identities) > 1 else "identified" if parts and parts[0]["section_path"] else "unknown"
    single = parts[0] if status == "identified" else {}
    return {"section_context_version": 1, "section_source": "markdown_heading",
            "section_status": status, "section_path": single.get("section_path", []),
            "section_title": single.get("section_title", ""),
            "section_field_no": single.get("section_field_no", ""),
            "section_segments": parts if status == "mixed" else []}


def annotate_source_sections(chunks: List[Dict[str, Any]], markdown: str) -> int:
    """Annotate existing chunks only when their unchanged body can be located in source.

    Duplicate text with different heading ownership is ambiguous, never guessed.
    Mixed chunks retain per-span ownership instead of inheriting one field for all text.
    """
    sections = markdown_sections(markdown)
    starts = [s["start"] for s in sections]
    normalized_markdown = None
    normalized_sections = None
    normalized_starts = None
    changed = 0
    cursor = 0
    for chunk in chunks:
        if chunk.get("section_context_version") == 1 and chunk.get("section_status") in ("identified", "mixed"):
            continue
        if chunk.get("modality", "text") != "text":
            continue
        body = chunk.get("content", "")
        if not body:
            continue
        position = markdown.find(body, cursor)
        if position < 0:
            position = markdown.find(body)
        metadata = _metadata(sections, starts, 0, 0)
        if position >= 0:
            candidate = _metadata(sections, starts, position, position + len(body))
            other = markdown.find(body)
            ambiguous = False
            while other >= 0:
                other_metadata = _metadata(sections, starts, other, other + len(body))
                if any(candidate[k] != other_metadata[k] for k in ("section_path", "section_field_no", "section_segments")):
                    ambiguous = True
                    break
                other = markdown.find(body, other + 1)
            if not ambiguous:
                metadata = candidate
                cursor = position + 1
        else:
            # Historic splitters may trim/wrap whitespace. Accept whitespace-only
            # differences for a single proven section; never invent mixed-span offsets.
            if normalized_markdown is None:
                normalized_markdown = re.sub(r"\s+", " ", markdown)
                normalized_sections = [dict(s) for s in sections]
                runs = [(m.start(), m.end()) for m in re.finditer(r"\s+", markdown)]
                ends = [right for _, right in runs]
                removed = [0]
                for left, right in runs:
                    removed.append(removed[-1] + right - left - 1)
                def normalized_offset(position):
                    index = bisect.bisect_right(ends, position)
                    if index < len(runs) and runs[index][0] < position:
                        return runs[index][0] - removed[index] + 1
                    return position - removed[index]
                for section in normalized_sections:
                    section["start"] = normalized_offset(section["start"])
                    section["end"] = normalized_offset(section["end"])
                normalized_starts = [s["start"] for s in normalized_sections]
            normalized_body = re.sub(r"\s+", " ", body)
            found = normalized_markdown.find(normalized_body)
            candidates = []
            while found >= 0:
                candidates.append(_metadata(normalized_sections, normalized_starts, found, found + len(normalized_body)))
                found = normalized_markdown.find(normalized_body, found + 1)
            if candidates and all(c["section_status"] == "identified" for c in candidates):
                identities = {(tuple(c["section_path"]), c["section_field_no"]) for c in candidates}
                if len(identities) == 1:
                    metadata = candidates[0]
                    metadata["section_source"] = "markdown_heading_whitespace_match"
        if any(chunk.get(k) != v for k, v in metadata.items()):
            chunk.update(metadata)
            changed += 1
    return changed


def section_label(chunk: Dict[str, Any]) -> str:
    path = chunk.get("section_path") or []
    return " > ".join(path) if isinstance(path, list) and path else "章节未确定"
