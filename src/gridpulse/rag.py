"""Search over public energy reports (Transelectrica, ANRE) for the agent's third tool.

Pipeline: PDF from the corpus list -> raw zone -> text per page (Azure AI Document Intelligence
when configured, pypdf otherwise) -> ~1,200-character chunks that never cross a page, so every
chunk cites one page -> multilingual embeddings computed locally (no API cost) -> pgvector.
"""

import hashlib
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import fsspec
import httpx
import numpy as np
import psycopg
import yaml

log = logging.getLogger(__name__)

CORPUS = Path(__file__).resolve().parents[2] / "docs" / "corpus.yaml"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIM = 384
CHUNK_CHARS = 1200
OVERLAP_CHARS = 200

SCHEMA_SQL = f"""
create extension if not exists vector;
create schema if not exists rag;
create table if not exists rag.documents (
    doc_id       text primary key,
    title        text not null,
    publisher    text,
    year         integer,
    url          text not null,
    sha256       text not null,
    n_pages      integer not null,
    parser       text not null,
    ingested_at  timestamptz not null default now()
);
create table if not exists rag.chunks (
    doc_id     text not null references rag.documents on delete cascade,
    chunk_id   integer not null,
    page       integer not null,
    text       text not null,
    embedding  vector({DIM}) not null,
    primary key (doc_id, chunk_id)
);
create index if not exists chunks_embedding_hnsw
    on rag.chunks using hnsw (embedding vector_cosine_ops);
"""


@dataclass(frozen=True)
class Chunk:
    page: int
    text: str


@dataclass(frozen=True)
class Hit:
    doc_id: str
    title: str
    year: int | None
    url: str
    page: int
    text: str
    score: float


def load_corpus(path: Path = CORPUS) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def chunk_pages(pages: list[str], size: int = CHUNK_CHARS, overlap: int = OVERLAP_CHARS):
    """Split each page into overlapping windows, cutting at sentence or line ends when possible."""
    chunks = []
    for page_no, raw in enumerate(pages, start=1):
        text = re.sub(r"[ \t]+", " ", raw)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                cut = max(
                    text.rfind(". ", start + size // 2, end),
                    text.rfind("\n", start + size // 2, end),
                )
                if cut > start:
                    end = cut + 1
            piece = text[start:end].strip()
            if len(piece) >= 80:  # page numbers, headers and other crumbs are not worth a vector
                chunks.append(Chunk(page_no, piece))
            if end >= len(text):
                break
            start = max(end - overlap, start + 1)
    return chunks


def pages_with_pypdf(data: bytes) -> list[str]:
    import io

    from pypdf import PdfReader

    return [(p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages]


def pages_with_document_intelligence(data: bytes) -> list[str]:
    """Azure AI Document Intelligence, prebuilt-layout: better tables and reading order."""
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
    from azure.core.credentials import AzureKeyCredential

    client = DocumentIntelligenceClient(
        os.environ["AZURE_DOCINTEL_ENDPOINT"], AzureKeyCredential(os.environ["AZURE_DOCINTEL_KEY"])
    )
    result = client.begin_analyze_document(
        "prebuilt-layout", AnalyzeDocumentRequest(bytes_source=data)
    ).result()
    pages: dict[int, list[str]] = {p.page_number: [] for p in result.pages}
    for para in result.paragraphs or []:
        page = para.bounding_regions[0].page_number if para.bounding_regions else 1
        pages.setdefault(page, []).append(para.content)
    return ["\n".join(pages[n]) for n in sorted(pages)]


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding

    return TextEmbedding(EMBEDDING_MODEL)


def embed(texts: list[str]) -> np.ndarray:
    vectors = np.array(list(_embedder().embed(texts)), dtype=np.float32)
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def init_schema(conn: psycopg.Connection) -> None:
    with conn.transaction():
        conn.execute(SCHEMA_SQL)


def ingest(conn: psycopg.Connection, raw_root: str, corpus: list[dict] | None = None) -> dict:
    """Download, parse, chunk, embed and store each document. Unchanged PDFs are skipped."""
    from pgvector.psycopg import register_vector

    init_schema(conn)
    register_vector(conn)
    parser = "document_intelligence" if os.environ.get("AZURE_DOCINTEL_ENDPOINT") else "pypdf"
    stats = {"ingested": 0, "unchanged": 0, "chunks": 0}
    with httpx.Client(
        timeout=120, follow_redirects=True, headers={"User-Agent": "gridpulse-ro"}
    ) as client:
        for doc in corpus or load_corpus():
            path = f"{raw_root.rstrip('/')}/docs/{doc['id']}.pdf"
            fs, fpath = fsspec.core.url_to_fs(path)
            if fs.exists(fpath):
                data = fs.cat(fpath)
            else:
                resp = client.get(doc["url"])
                resp.raise_for_status()
                data = resp.content
                fs.makedirs(fpath.rsplit("/", 1)[0], exist_ok=True)
                fs.pipe(fpath, data)
            sha = hashlib.sha256(data).hexdigest()
            row = conn.execute(
                "select sha256, parser from rag.documents where doc_id = %s", (doc["id"],)
            ).fetchone()
            if row == (sha, parser):
                stats["unchanged"] += 1
                continue
            pages = (
                pages_with_document_intelligence
                if parser == "document_intelligence"
                else pages_with_pypdf
            )(data)
            chunks = chunk_pages(pages)
            vectors = embed([c.text for c in chunks])
            with conn.transaction():
                conn.execute("delete from rag.documents where doc_id = %s", (doc["id"],))
                conn.execute(
                    """
                    insert into rag.documents
                        (doc_id, title, publisher, year, url, sha256, n_pages, parser)
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        doc["id"],
                        doc["title"],
                        doc.get("publisher"),
                        doc.get("year"),
                        doc["url"],
                        sha,
                        len(pages),
                        parser,
                    ),
                )
                with conn.cursor().copy(
                    "copy rag.chunks (doc_id, chunk_id, page, text, embedding) from stdin"
                ) as copy:
                    copy.set_types(["text", "int4", "int4", "text", "vector"])
                    for i, (c, v) in enumerate(zip(chunks, vectors, strict=True)):
                        copy.write_row((doc["id"], i, c.page, c.text, v))
            log.info("%s: %d pages, %d chunks (%s)", doc["id"], len(pages), len(chunks), parser)
            stats["ingested"] += 1
            stats["chunks"] += len(chunks)
    return stats


def search(conn: psycopg.Connection, query: str, k: int = 5) -> list[Hit]:
    from pgvector.psycopg import register_vector

    register_vector(conn)
    q = embed([query])[0]
    rows = conn.execute(
        """
        select c.doc_id, d.title, d.year, d.url, c.page, c.text,
               1 - (c.embedding <=> %s) as score
        from rag.chunks as c join rag.documents as d using (doc_id)
        order by c.embedding <=> %s
        limit %s
        """,
        (q, q, k),
    ).fetchall()
    return [Hit(*r) for r in rows]
