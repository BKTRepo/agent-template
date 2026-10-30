# -*- coding: utf-8 -*-
"""PDF文档加载与分块处理"""

from pathlib import Path
from typing import Union

from langchain_community.document_loaders import PyMuPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from configure import PROJECT_CONFIG


def load_pdf(file_path: Union[str, Path]) -> list[Document]:
    """加载单个PDF文件，返回文档列表"""
    loader = PyMuPDFLoader(str(file_path))
    docs = loader.load()
    # 清洗文本：去除多余空白
    for doc in docs:
        doc.page_content = doc.page_content.strip()
    return [doc for doc in docs if doc.page_content]


def load_all_pdfs(data_dir=None) -> list[Document]:
    """加载data目录下所有PDF文件"""
    data_path = Path(data_dir or PROJECT_CONFIG.datagram_path)
    all_docs = []
    for pdf_file in sorted(data_path.glob("*.pdf")):
        docs = load_pdf(pdf_file)
        print(f"  已加载: {pdf_file.name} ({len(docs)} 页)")
        all_docs.extend(docs)
    return all_docs


def split_documents(docs: list[Document]) -> list[Document]:
    """将文档分割为较小的文本块"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=PROJECT_CONFIG.CHUNK_SIZE,
        chunk_overlap=PROJECT_CONFIG.CHUNK_OVERLAP,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
        keep_separator=True,
    )
    chunks = splitter.split_documents(docs)
    # 为每个chunk添加索引元数据
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i
    return chunks
