"""Document loaders for all supported input formats.

Provides a factory-pattern DocumentLoader that dispatches to format-specific
parsers based on file extension. Each loader produces RawSection objects
preserving document structure (headers, hierarchy, page numbers).

Supported formats: Markdown, PDF, Word (docx), JSON, CSV, plain text.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

import chardet
import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Raw Section Model ──────────────────────────────────────────────────────


class RawSection(BaseModel):
    """A raw text section extracted from a document before chunking.

    Attributes:
        content: The text content of this section.
        source: Original file path or identifier.
        section_title: Title of this section (e.g., header text).
        hierarchy: Breadcrumb path of headers leading to this section.
        page_number: Page number for paginated formats (PDF, Word).
        frontmatter: Parsed YAML frontmatter dict, if present.
    """

    content: str
    source: str
    section_title: str | None = None
    hierarchy: list[str] = Field(default_factory=list)
    page_number: int | None = None
    frontmatter: dict[str, Any] | None = None


# ── Format-Specific Loaders ───────────────────────────────────────────────


def _read_file_bytes(file_path: Path) -> bytes:
    """Read file as bytes."""
    return file_path.read_bytes()


def _decode_content(raw_bytes: bytes) -> str:
    """Decode bytes to string with encoding detection.

    Tries UTF-8 first, falls back to chardet detection.
    """
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        detected = chardet.detect(raw_bytes)
        encoding = detected.get("encoding", "utf-8") or "utf-8"
        logger.info("Detected encoding: %s (confidence: %s)", encoding, detected.get("confidence"))
        return raw_bytes.decode(encoding, errors="replace")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any] | None, str]:
    """Extract YAML frontmatter from text.

    Returns (frontmatter_dict, remaining_text). If no frontmatter found,
    returns (None, original_text).
    """
    pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    match = pattern.match(text)
    if match:
        try:
            fm = yaml.safe_load(match.group(1))
            if isinstance(fm, dict):
                remaining = text[match.end() :]
                return fm, remaining
        except yaml.YAMLError:
            logger.warning("Failed to parse YAML frontmatter, treating as content")
    return None, text


def _load_markdown(file_path: Path, content: str) -> list[RawSection]:
    """Load markdown file preserving header hierarchy.

    Splits on headers (# through ####) and tracks the hierarchy stack.
    Content before the first header becomes its own section.
    """
    source = str(file_path)
    frontmatter, body = _parse_frontmatter(content)

    sections: list[RawSection] = []
    # Track hierarchy: {level: title}
    hierarchy_stack: dict[int, str] = {}
    current_content_lines: list[str] = []
    current_title: str | None = None
    current_level: int = 0

    header_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    lines = body.split("\n")
    for line in lines:
        match = header_pattern.match(line)
        if match:
            # Flush previous section
            section_text = "\n".join(current_content_lines).strip()
            if section_text:
                hierarchy = [hierarchy_stack[k] for k in sorted(hierarchy_stack) if k < current_level]
                if current_title:
                    hierarchy.append(current_title)
                sections.append(
                    RawSection(
                        content=section_text,
                        source=source,
                        section_title=current_title,
                        hierarchy=hierarchy,
                        frontmatter=frontmatter,
                    )
                )

            # Update hierarchy
            level = len(match.group(1))
            title = match.group(2).strip()
            current_level = level
            current_title = title
            hierarchy_stack[level] = title
            # Clear deeper levels
            for k in list(hierarchy_stack):
                if k > level:
                    del hierarchy_stack[k]
            current_content_lines = []
        else:
            current_content_lines.append(line)

    # Flush final section
    section_text = "\n".join(current_content_lines).strip()
    if section_text:
        hierarchy = [hierarchy_stack[k] for k in sorted(hierarchy_stack) if k < current_level]
        if current_title:
            hierarchy.append(current_title)
        sections.append(
            RawSection(
                content=section_text,
                source=source,
                section_title=current_title,
                hierarchy=hierarchy,
                frontmatter=frontmatter,
            )
        )

    # If no sections found (no headers), treat entire content as one section
    if not sections and body.strip():
        sections.append(
            RawSection(
                content=body.strip(),
                source=source,
                section_title=None,
                hierarchy=[],
                frontmatter=frontmatter,
            )
        )

    return sections


def _load_json(file_path: Path, content: str) -> list[RawSection]:
    """Load JSON file, flattening nested structures into text sections.

    For top-level objects: each key becomes a section.
    For arrays: each element becomes a section.
    Nested objects are formatted as readable key-value text.
    """
    source = str(file_path)
    data = json.loads(content)

    sections: list[RawSection] = []

    def _format_value(value: Any, indent: int = 0) -> str:
        """Format a JSON value as readable text."""
        prefix = "  " * indent
        if isinstance(value, dict):
            lines = []
            for k, v in value.items():
                formatted_key = k.replace("_", " ").title()
                if isinstance(v, dict | list):
                    lines.append(f"{prefix}{formatted_key}:")
                    lines.append(_format_value(v, indent + 1))
                else:
                    lines.append(f"{prefix}{formatted_key}: {v}")
            return "\n".join(lines)
        elif isinstance(value, list):
            lines = []
            for item in value:
                if isinstance(item, dict | list):
                    lines.append(_format_value(item, indent))
                    lines.append("")  # blank line separator
                else:
                    lines.append(f"{prefix}- {item}")
            return "\n".join(lines)
        else:
            return f"{prefix}{value}"

    if isinstance(data, dict):
        for key, value in data.items():
            formatted_key = key.replace("_", " ").title()
            section_content = _format_value(value)
            sections.append(
                RawSection(
                    content=section_content,
                    source=source,
                    section_title=formatted_key,
                    hierarchy=[formatted_key],
                )
            )
    elif isinstance(data, list):
        for i, item in enumerate(data):
            section_content = _format_value(item)
            title = f"Item {i + 1}"
            if isinstance(item, dict) and "name" in item:
                title = str(item["name"])
            elif isinstance(item, dict) and "title" in item:
                title = str(item["title"])
            sections.append(
                RawSection(
                    content=section_content,
                    source=source,
                    section_title=title,
                    hierarchy=[title],
                )
            )
    else:
        sections.append(
            RawSection(
                content=str(data),
                source=source,
                section_title=None,
                hierarchy=[],
            )
        )

    return sections


def _load_csv(file_path: Path, content: str) -> list[RawSection]:
    """Load CSV file, each row becomes a section with column headers as context."""
    source = str(file_path)
    sections: list[RawSection] = []

    reader = csv.DictReader(io.StringIO(content))
    for i, row in enumerate(reader):
        # Format each row as key: value pairs
        lines = [f"{col}: {val}" for col, val in row.items() if val]
        section_content = "\n".join(lines)
        # Try to use first column value as title
        first_val = next(iter(row.values()), None) if row else None
        title = str(first_val) if first_val else f"Row {i + 1}"

        sections.append(
            RawSection(
                content=section_content,
                source=source,
                section_title=title,
                hierarchy=[title],
            )
        )

    return sections


def _load_text(file_path: Path, content: str) -> list[RawSection]:
    """Load plain text file as a single section."""
    return [
        RawSection(
            content=content.strip(),
            source=str(file_path),
            section_title=file_path.stem,
            hierarchy=[],
        )
    ]


def _load_pdf(file_path: Path) -> list[RawSection]:
    """Load PDF using unstructured library.

    Falls back to a simple error if unstructured is not installed.
    """
    source = str(file_path)
    try:
        from unstructured.partition.pdf import partition_pdf

        elements = partition_pdf(str(file_path))
        sections: list[RawSection] = []
        current_page = 1

        for element in elements:
            page = getattr(element.metadata, "page_number", current_page) or current_page
            current_page = page
            sections.append(
                RawSection(
                    content=str(element),
                    source=source,
                    section_title=getattr(element.metadata, "section", None),
                    hierarchy=[],
                    page_number=page,
                )
            )

        return sections
    except ImportError:
        raise ImportError(
            "PDF loading requires the 'unstructured' library. "
            "Install with: pip install 'unstructured[all-docs]'"
        )


def _load_docx(file_path: Path) -> list[RawSection]:
    """Load Word document using unstructured library.

    Falls back to a simple error if unstructured is not installed.
    """
    source = str(file_path)
    try:
        from unstructured.partition.docx import partition_docx

        elements = partition_docx(str(file_path))
        sections: list[RawSection] = []

        for element in elements:
            page = getattr(element.metadata, "page_number", None)
            sections.append(
                RawSection(
                    content=str(element),
                    source=source,
                    section_title=getattr(element.metadata, "section", None),
                    hierarchy=[],
                    page_number=page,
                )
            )

        return sections
    except ImportError:
        raise ImportError(
            "Word document loading requires the 'unstructured' library. "
            "Install with: pip install 'unstructured[all-docs]'"
        )


# ── Supported Format Registry ─────────────────────────────────────────────

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".pdf": "pdf",
    ".docx": "word",
    ".json": "json",
    ".csv": "csv",
    ".txt": "text",
}


# ── Document Loader ───────────────────────────────────────────────────────


class DocumentLoader:
    """Factory-pattern document loader that dispatches to format-specific parsers.

    Usage:
        loader = DocumentLoader()
        sections = loader.load("path/to/document.md")

    Supported formats: .md, .markdown, .pdf, .docx, .json, .csv, .txt
    """

    def load(self, file_path: str | Path, content_type: str | None = None) -> list[RawSection]:
        """Load a document and return structured sections.

        Args:
            file_path: Path to the document file.
            content_type: Optional format hint (overrides extension detection).

        Returns:
            List of RawSection objects representing document structure.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If file format is not supported.
            ImportError: If required library for format is not installed.
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Document not found: {path}")

        # Determine format
        fmt = content_type
        if fmt is None:
            ext = path.suffix.lower()
            fmt = SUPPORTED_EXTENSIONS.get(ext)
            if fmt is None:
                supported = ", ".join(sorted(SUPPORTED_EXTENSIONS.keys()))
                raise ValueError(
                    f"Unsupported file format: '{ext}'. "
                    f"Supported formats: {supported}. "
                    f"Use content_type parameter to specify format explicitly."
                )

        # Dispatch to format-specific loader
        if fmt in ("pdf",):
            return _load_pdf(path)
        elif fmt in ("word",):
            return _load_docx(path)
        else:
            # Text-based formats: read and decode
            raw_bytes = _read_file_bytes(path)
            content = _decode_content(raw_bytes)

            if fmt == "markdown":
                return _load_markdown(path, content)
            elif fmt == "json":
                return _load_json(path, content)
            elif fmt == "csv":
                return _load_csv(path, content)
            elif fmt == "text":
                return _load_text(path, content)
            else:
                raise ValueError(f"Unknown content type: {fmt}")


def load_document(file_path: str | Path, content_type: str | None = None) -> list[RawSection]:
    """Convenience function to load a document.

    Delegates to DocumentLoader().load() for simple one-shot usage.

    Args:
        file_path: Path to the document file.
        content_type: Optional format hint.

    Returns:
        List of RawSection objects.
    """
    loader = DocumentLoader()
    return loader.load(file_path, content_type)
