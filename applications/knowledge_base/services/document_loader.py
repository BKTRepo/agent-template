from dataclasses import dataclass, field
from pathlib import Path
from applications.knowledge_base.processing.markdown_conversion import _convert

@dataclass
class LangchainDocument:
    page_content: str
    metadata: dict = field(default_factory=dict)

def load_document_pages(file_path, file_type):
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        text = _convert(Path(file_path).read_bytes(), Path(file_path).stem + '.' + file_type, directory)
    return [LangchainDocument(text)]
