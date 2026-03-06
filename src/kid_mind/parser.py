"""KID PDF processing library: PDF→markdown, section splitting, chunking, metadata.

Pipeline: KID PDF → Docling (markdown) → regex section split →
          semantic sub-chunk (all sections) → metadata extraction → chunk dicts
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

from kid_mind.config import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    OPENAI_EMBEDDING_MODEL,
)

log = logging.getLogger(__name__)


# ── Section splitting ─────────────────────────────────────────────────────────

# Only match lines that start with "## " and contain a mandatory heading phrase.
# Covers both PRIIPs KIDs (EU-mandated headings) and old-format KIIDs (iShares GB ISINs).
# Sub-headings like "## Type", "## Objectives" are NOT in this list, so they stay
# inside their parent section.
_SECTION_PATTERNS = [
    # PRIIPs KID headings
    ("product_and_description", r"^#{2,3} .*What is this product"),
    ("risks_and_return", r"^#{2,3} .*What are the risks"),
    ("risks_and_return", r"^#{2,3} .*Performance Scenarios"),
    ("unable_to_pay", r"^#{2,3} .*What happens if .+? unable to pay"),
    ("costs", r"^#{2,3} .*What are the costs"),
    ("holding_period", r"^#{2,3} .*How long should I hold"),
    ("complaints", r"^#{2,3} .*How can I complain"),
    ("other_info", r"^#{2,3} .*Other relevant information"),
    # KIID headings (old iShares format — same 4-chunk structure)
    ("product_and_description", r"^## .*Objectives and Investment Policy"),
    ("risks_and_return", r"^## .*Risk and Reward Profile"),
    ("past_performance", r"^## .*Past Performance"),
    ("costs", r"^## .*Charges$"),
    ("practical_info", r"^## .*Practical Information"),
]


def _match_section(line: str) -> str | None:
    """Return section key if line matches a mandatory heading, else None."""
    for key, pattern in _SECTION_PATTERNS:
        if re.match(pattern, line, re.IGNORECASE):
            return key
    return None


def split_sections(markdown: str) -> dict[str, str]:
    """Split Docling markdown into KID sections by EU-mandated headings.

    Returns a dict mapping section keys to their text content.
    The "preamble" key contains everything before the first matched heading.
    """
    sections: dict[str, list[str]] = {"preamble": []}
    current = "preamble"

    for line in markdown.split("\n"):
        key = _match_section(line)
        if key is not None:
            current = key
            if key not in sections:
                sections[key] = []
        sections.setdefault(current, []).append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items() if v}


_SRI_PATTERN = re.compile(
    r"(?:classified\s+this\s+(?:product|fund)\s+as\s+\d\s+out\s+of\s+7"
    r"|summary\s+risk\s+indicator"
    r"|risk\s+indicator\s+is\s+a\s+guide"
    r"|potential\s+losses\s+from\s+futu"
    r"|be\s+aware\s+of\s+currency\s+risk"
    r"|besides\s+the\s+risks\s+included)",
    re.IGNORECASE,
)


def _relocate_sri_paragraphs(sections: dict[str, str]) -> dict[str, str]:
    """Move SRI risk-indicator paragraphs into risks_and_return.

    Docling sometimes extracts the SRI classification text out of page order,
    placing it inside 'costs' (SPDR) or leaving it in 'product_and_description'
    (some iShares). This function detects SRI-related paragraphs in the wrong
    section and moves them to 'risks_and_return'.
    """
    donor_keys = ["costs", "product_and_description"]
    relocated = []

    for key in donor_keys:
        if key not in sections:
            continue
        paragraphs = re.split(r"\n{2,}", sections[key])
        keep = []
        for para in paragraphs:
            if _SRI_PATTERN.search(para):
                relocated.append(para)
            else:
                keep.append(para)
        if len(keep) < len(paragraphs):
            sections[key] = "\n\n".join(keep).strip()

    if relocated:
        risk_text = sections.get("risks_and_return", "")
        sections["risks_and_return"] = (risk_text + "\n\n" + "\n\n".join(relocated)).strip()

    return sections


def _build_chunks(sections: dict[str, str]) -> list[dict]:
    """Build the 4-chunk structure from parsed sections.

    Returns list of dicts with keys: section, text.
    """
    chunks = []

    # 1. product_and_description = preamble + "What is this product?"
    product_parts = []
    if "preamble" in sections:
        product_parts.append(sections["preamble"])
    if "product_and_description" in sections:
        product_parts.append(sections["product_and_description"])
    if product_parts:
        chunks.append(
            {
                "section": "product_and_description",
                "text": "\n\n".join(product_parts),
            }
        )

    # 2. risks_and_return (+ past_performance for KIIDs)
    risk_parts = []
    if "risks_and_return" in sections:
        risk_parts.append(sections["risks_and_return"])
    if "past_performance" in sections:
        risk_parts.append(sections["past_performance"])
    if risk_parts:
        chunks.append(
            {
                "section": "risks_and_return",
                "text": "\n\n".join(risk_parts),
            }
        )

    # 3. costs
    if "costs" in sections:
        chunks.append(
            {
                "section": "costs",
                "text": sections["costs"],
            }
        )

    # 4. tail = unable_to_pay + holding_period + complaints + other_info
    tail_parts = []
    for key in ["unable_to_pay", "holding_period", "complaints", "other_info", "practical_info"]:
        if key in sections:
            tail_parts.append(sections[key])
    if tail_parts:
        chunks.append(
            {
                "section": "tail",
                "text": "\n\n".join(tail_parts),
            }
        )

    return chunks


# ── Metadata extraction ───────────────────────────────────────────────────────

_MANUFACTURER_RE = re.compile(
    r"What happens if (.+?) is unable to pay",
    re.IGNORECASE,
)

# ── Risk level extraction ────────────────────────────────────────────────────

# PRIIPs format: "We have classified this product as 4 out of 7"
_RISK_PRIIPS_RE = re.compile(
    r"classified\s+this\s+(?:product|fund)\s+as\s+(\d)\s+out\s+of\s+7",
    re.IGNORECASE,
)

# Old iShares KIID format: "The Fund is rated five due to..."
_RISK_KIID_RE = re.compile(
    r"(?:Fund|product)\s+is\s+rated\s+(\w+)\s+due\s+to",
    re.IGNORECASE,
)

_WORD_TO_INT = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
}


def _extract_risk_level(markdown: str) -> int | None:
    """Extract the SRI risk level (1-7) from KID/KIID markdown text."""
    # PRIIPs format
    m = _RISK_PRIIPS_RE.search(markdown)
    if m:
        level = int(m.group(1))
        if 1 <= level <= 7:
            return level

    # Old KIID word format
    m = _RISK_KIID_RE.search(markdown)
    if m:
        word = m.group(1).lower()
        return _WORD_TO_INT.get(word)

    return None


# ── Launch year extraction ──────────────────────────────────────────────────

_LAUNCH_YEAR_RE = re.compile(r"was\s+launched\s+in\s+(\d{4})", re.IGNORECASE)


def extract_launch_year(markdown: str) -> int | None:
    """Extract the fund/share-class launch year from KID markdown text.

    When multiple matches exist (fund vs share class), take the last match
    which typically refers to the specific share class ISIN.
    """
    matches = _LAUNCH_YEAR_RE.findall(markdown)
    if not matches:
        return None
    year = int(matches[-1])
    if 1990 <= year <= 2100:
        return year
    return None


# ── KID date extraction ─────────────────────────────────────────────────────

# "This document is dated 14/02/2025" (Vanguard, SPDR)
_KID_DATE_SLASH_RE = re.compile(r"document\s+is\s+dated\s+(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE)

# "Accurate as of: 15 January 2025" (iShares, SPDR)
# "accurate as at 31 January 2026" (Xtrackers ETCs)
# "document is dated 9 April 2025" (iShares named-month variant)
_KID_DATE_NAMED_RE = re.compile(
    r"(?:Accurate\s+as\s+(?:of|at)[:\s]+|document\s+is\s+dated\s+)"
    r"(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})",
    re.IGNORECASE,
)

_MONTH_TO_NUM = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def extract_kid_date(markdown: str) -> str | None:
    """Extract the KID document date and return as ISO format YYYY-MM-DD."""
    # Try DD/MM/YYYY format first
    m = _KID_DATE_SLASH_RE.search(markdown)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        return f"{year}-{month}-{day}"

    # Try "DD Month YYYY" format
    m = _KID_DATE_NAMED_RE.search(markdown)
    if m:
        day = int(m.group(1))
        month_num = _MONTH_TO_NUM.get(m.group(2).lower())
        year = m.group(3)
        if month_num:
            return f"{year}-{month_num:02d}-{day:02d}"

    return None


_GENERIC_HEADING_RE = re.compile(
    r"^#{1,3}\s*(Key Information Document|Key Investor Information|Purpose|Product)\b",
    re.IGNORECASE,
)

_PRODUCT_LINE_RE = re.compile(r"^Product:\s+(.+)", re.IGNORECASE)

_NAME_OF_PRODUCT_RE = re.compile(r"^Name of Product:", re.IGNORECASE)

_SKIP_LINE_RE = re.compile(
    r"^(ISIN|Currency|Date|Manufacturer|This document|Call |More |The |<!--)",
    re.IGNORECASE,
)


def _clean_product_name(name: str) -> str:
    """Strip trailing fund identifiers, share class info, and normalize whitespace."""
    name = re.split(r"\s*\((?:the\s+)?['\"]", name)[0]
    name = re.split(r"\s+Share\s+class:", name, flags=re.IGNORECASE)[0]
    name = re.split(r",\s*ISIN:", name, flags=re.IGNORECASE)[0]
    name = re.split(r"\s+-\s+\(", name)[0]
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _extract_product_name(sections: dict[str, str]) -> str:
    """Extract product name from the preamble section."""
    preamble = sections.get("preamble", "")
    lines = preamble.split("\n")

    # 1. "Product: <name>" line (Vanguard style)
    for line in lines:
        m = _PRODUCT_LINE_RE.match(line.strip())
        if m:
            return _clean_product_name(m.group(1))

    # 2. "Name of Product:" + next non-empty line (Xtrackers DE style)
    for i, line in enumerate(lines):
        if _NAME_OF_PRODUCT_RE.match(line.strip()):
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip()
                if candidate and not candidate.startswith("#"):
                    return _clean_product_name(candidate)

    # 3. Non-generic headings (SPDR, Xtrackers, iShares KIID)
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        if _GENERIC_HEADING_RE.match(stripped):
            continue
        heading = re.sub(r"^#+\s*", "", stripped)
        cleaned = _clean_product_name(heading)
        if len(cleaned) >= 10:
            return cleaned

    # 4. First non-metadata paragraph line (iShares PRIIPs)
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or len(stripped) < 10:
            continue
        if _SKIP_LINE_RE.match(stripped):
            continue
        return _clean_product_name(stripped)

    return ""


def _extract_manufacturer(text: str) -> str:
    """Extract manufacturer from 'What happens if X is unable to pay' heading."""
    m = _MANUFACTURER_RE.search(text)
    return m.group(1).strip() if m else ""


def extract_metadata(
    isin: str,
    provider: str,
    markdown: str,
    sections: dict[str, str],
    isin_record: dict | None,
) -> dict:
    """Extract structured metadata from markdown text and ISIN record."""
    product_name = ""
    if isin_record:
        product_name = isin_record.get("name", "")
    # Prefer PDF-extracted name when ISIN record name looks slug-derived
    if not product_name or product_name == product_name.lower():
        pdf_name = _extract_product_name(sections)
        if pdf_name:
            product_name = pdf_name

    manufacturer = _extract_manufacturer(markdown)

    risk_level = _extract_risk_level(markdown)
    if risk_level is None:
        log.warning("%s: could not extract risk level", isin)

    launch_year = extract_launch_year(markdown)
    kid_date = extract_kid_date(markdown)

    return {
        "isin": isin,
        "product_name": product_name,
        "provider": provider,
        "manufacturer": manufacturer,
        "risk_level": risk_level,
        "launch_year": launch_year,
        "kid_date": kid_date,
    }


def _metadata_prefix(meta: dict) -> str:
    """Build the metadata prefix string prepended to every chunk."""
    parts = [f"ISIN: {meta['isin']}"]
    if meta.get("product_name"):
        parts.append(f"Product: {meta['product_name']}")
    parts.append(f"Provider: {meta['provider']}")
    return " | ".join(parts)


# ── Lazy-loaded heavy dependencies ───────────────────────────────────────────

_converter = None
_init_lock = threading.Lock()


def _get_converter() -> object:
    """Lazily initialize the Docling PDF converter (thread-safe)."""
    global _converter  # noqa: PLW0603
    if _converter is None:
        with _init_lock:
            if _converter is None:
                log.info("Initializing Docling converter (this may take a moment)...")
                from docling.datamodel.base_models import InputFormat
                from docling.datamodel.pipeline_options import (
                    PdfPipelineOptions,
                    TableFormerMode,
                    TableStructureOptions,
                )
                from docling.document_converter import DocumentConverter, PdfFormatOption

                pipeline_options = PdfPipelineOptions()
                pipeline_options.do_ocr = False
                pipeline_options.do_table_structure = True
                pipeline_options.table_structure_options = TableStructureOptions(
                    do_cell_matching=True,
                    mode=TableFormerMode.ACCURATE,
                )
                _converter = DocumentConverter(
                    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
                )
    return _converter


# ── Core pipeline ─────────────────────────────────────────────────────────────


def _pdf_to_markdown(pdf_path: Path) -> str:
    """Convert a PDF to markdown using Docling."""
    converter = _get_converter()
    result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown()


_chunker_instance = None
_chunker_lock = threading.Lock()
_CHUNKER_FAILED = object()  # sentinel: initialization was attempted and failed
_CHUNKER_MAX_TOKENS = 8192


def _get_chunker() -> object | None:
    """Lazily initialize the Chonkie SemanticChunker (thread-safe).

    Returns None if OPENAI_API_KEY is not set or initialization fails.
    """
    global _chunker_instance  # noqa: PLW0603

    if _chunker_instance is _CHUNKER_FAILED:
        return None
    if _chunker_instance is not None:
        return _chunker_instance

    with _chunker_lock:
        if _chunker_instance is _CHUNKER_FAILED:
            return None
        if _chunker_instance is not None:
            return _chunker_instance

        if not OPENAI_API_KEY:
            log.info("OPENAI_API_KEY not set — semantic sub-chunking disabled")
            _chunker_instance = _CHUNKER_FAILED
            return None

        model = EMBEDDING_MODEL or OPENAI_EMBEDDING_MODEL
        try:
            import tiktoken
            from chonkie import OpenAIEmbeddings, SemanticChunker

            kwargs: dict = {"model": model, "api_key": OPENAI_API_KEY}
            if OPENAI_API_BASE:
                kwargs["base_url"] = OPENAI_API_BASE
            # Custom models need explicit tokenizer, dimension, max_tokens
            if model not in OpenAIEmbeddings.AVAILABLE_MODELS:
                kwargs["tokenizer"] = tiktoken.get_encoding("cl100k_base")
                kwargs["dimension"] = EMBEDDING_DIMENSION
                kwargs["max_tokens"] = _CHUNKER_MAX_TOKENS

            embeddings = OpenAIEmbeddings(**kwargs)
            _chunker_instance = SemanticChunker(
                embedding_model=embeddings,
                threshold=0.2,
                chunk_size=2048,
                min_sentences_per_chunk=5,
                min_characters_per_sentence=50,
            )
            log.info("SemanticChunker ready: model=%s, api_base=%s", model, OPENAI_API_BASE or "default")
            return _chunker_instance
        except (ImportError, ValueError, RuntimeError, OSError):
            log.warning("Failed to initialize SemanticChunker — falling back to no sub-chunking", exc_info=True)
            _chunker_instance = _CHUNKER_FAILED
            return None


def _semantic_subchunk(text: str) -> list[str]:
    """Split a section's text into semantic sub-chunks using Chonkie.

    Applied to every KID section (product, risks, costs, tail) to break
    long sections into embedding-friendly pieces at topic boundaries.
    Falls back to returning text as-is if the chunker is unavailable.
    """
    chunker = _get_chunker()
    if chunker is None:
        return [text]

    try:
        chunks = chunker.chunk(text)
        result = [c.text for c in chunks if c.text.strip()]
        return result if result else [text]
    except (ValueError, RuntimeError):
        log.warning("Semantic sub-chunking failed — returning text as single chunk", exc_info=True)
        return [text]


def _chunk_metadata(meta: dict, section: str, sub_index: int) -> dict:
    """Build per-chunk metadata, dropping empty values."""
    return {
        k: v
        for k, v in {
            "isin": meta["isin"],
            "product_name": meta["product_name"],
            "provider": meta["provider"],
            "risk_level": meta.get("risk_level"),
            "launch_year": meta.get("launch_year"),
            "kid_date": meta.get("kid_date"),
            "section": section,
            "sub_index": sub_index,
        }.items()
        if v is not None and v != ""
    }


def process_pdf(
    pdf_path: Path,
    isin: str,
    provider: str,
    isin_record: dict | None = None,
) -> list[dict]:
    """Process a single KID PDF into chunks with metadata.

    Returns list of dicts: {id, section, sub_index, text, metadata}.
    """
    # Step 1 — Convert PDF to markdown via Docling, then split into KID sections
    # (product_and_description, risks_and_return, costs, tail).
    # SRI paragraphs often land in the wrong section after splitting, so relocate them.
    markdown = _pdf_to_markdown(pdf_path)
    sections = split_sections(markdown)
    sections = _relocate_sri_paragraphs(sections)

    # Step 2 — Extract structured metadata (product name, risk level, launch year, etc.)
    # from the markdown + ISIN record, and build a human-readable prefix that gets
    # prepended to every chunk so the embedding captures fund identity.
    meta = extract_metadata(isin, provider, markdown, sections, isin_record)
    prefix = _metadata_prefix(meta)
    raw_chunks = _build_chunks(sections)

    # Step 3 — Handle edge cases where Docling produced no usable sections.
    # Fall back to storing the entire markdown as one chunk so nothing is lost.
    if not raw_chunks:
        log.warning("%s: no sections found — storing full document as single chunk", isin)
        raw_chunks = [{"section": "full_document", "text": markdown}]

    # If only 0-1 sections were found the PDF was likely mis-parsed — skip semantic
    # sub-chunking because Chonkie needs enough text to split meaningfully.
    degraded = len(raw_chunks) < 2
    if degraded:
        log.warning("%s: only %d section(s) — skipping semantic sub-chunking", isin, len(raw_chunks))

    # Step 4 — Produce final chunks. Each section is semantically sub-chunked
    # (unless degraded) and tagged with a unique id, section label, and metadata.
    # The metadata prefix is prepended so every chunk carries fund context.
    result = []
    for chunk in raw_chunks:
        section = chunk["section"]
        sub_texts = [chunk["text"]] if degraded else _semantic_subchunk(chunk["text"])

        for sub_idx, sub_text in enumerate(sub_texts):
            result.append(
                {
                    "id": f"{isin}_{section}_{sub_idx}",
                    "section": section,
                    "sub_index": sub_idx,
                    "text": f"{prefix}\n\n{sub_text}",
                    "metadata": _chunk_metadata(meta, section, sub_idx),
                }
            )

    return result
