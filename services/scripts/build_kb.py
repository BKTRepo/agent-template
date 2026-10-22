# -*- coding: utf-8 -*-
"""构建离线知识库脚本（写入 Chroma 本地库）

用法: python scripts/build_kb.py
"""

import time
import uuid

import _bootstrap  # noqa: F401
from applications.base.rag.chroma_store import chroma_store
from applications.base.rag.embeddings import get_embedding
from applications.base.rag.loader import load_all_pdfs, split_documents
from configure import PROJECT_CONFIG


def main():
    print("=" * 50)
    print("知识库构建（Chroma 本地模式）")
    print("=" * 50)

    print("\n[1/3] 加载 PDF 文档...")
    docs = load_all_pdfs(PROJECT_CONFIG.datagram_path)
    print(f"  共加载 {len(docs)} 页文档")
    if not docs:
        print("错误: 未找到 PDF，请检查 data/ 目录")
        return

    print("\n[2/3] 文本分块...")
    start = time.time()
    chunks = split_documents(docs)
    print(f"  共生成 {len(chunks)} 个文本块 (耗时 {time.time() - start:.1f}s)")

    print(f"\n[3/3] 向量化并写入 {PROJECT_CONFIG.chroma_path} ...")
    start = time.time()
    texts = [c.page_content for c in chunks]
    embeddings = get_embedding(texts)
    offline_kb_id = "offline"
    chroma_store.upsert_chunks(
        offline_kb_id,
        [
            {
                "doc_id": "offline",
                "chunk_id": str(uuid.uuid4()),
                "content": text,
                "embedding": emb,
            }
            for text, emb in zip(texts, embeddings)
        ],
    )
    print(f"  完成 (耗时 {time.time() - start:.1f}s)")
    print("\n" + "=" * 50)
    print("知识库构建成功！")
    print(f"  存储路径: {PROJECT_CONFIG.chroma_path}")
    print(f"  文本块数: {len(chunks)}")
    print("=" * 50)


if __name__ == "__main__":
    main()
