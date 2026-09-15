from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DocumentStatus(str, Enum):
    """Lifecycle of one document through the processing pipeline."""

    UPLOADED = "Uploaded"
    PROCESSING = "Processing"
    EMBEDDING = "Embedding"
    INDEXED = "Indexed"
    FAILED = "Failed"


@dataclass
class Folder:
    path: str
    name: str
    parent_path: Optional[str]
    document_count: int = 0


@dataclass
class DocumentRecord:
    category: str
    filename: str
    relative_path: str
    extension: str
    size: int
    sha256: Optional[str]
    status: str
    status_detail: Optional[str] = None
