import hashlib
import os

import numpy as np
import psycopg
import pytest

from gridpulse import rag


def test_chunks_never_cross_pages_and_overlap():
    page = ". ".join(f"Propoziția numărul {i} despre consumul de energie" for i in range(60))
    chunks = rag.chunk_pages([page, "scurt", page])
    assert {c.page for c in chunks} == {1, 3}  # page 2 is too short to keep
    assert all(len(c.text) <= rag.CHUNK_CHARS for c in chunks)
    p1 = [c.text for c in chunks if c.page == 1]
    assert len(p1) >= 2
    assert p1[0][-100:].split()[-1] in p1[1]  # consecutive chunks overlap


def test_corpus_entries_are_complete():
    corpus = rag.load_corpus()
    assert len({d["id"] for d in corpus}) == len(corpus) >= 4
    assert all(d["url"].startswith("https://") and d["title"] for d in corpus)


def fake_embed(texts):
    """Deterministic bag-of-words vectors: shared words -> similar vectors."""
    out = np.zeros((len(texts), rag.DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        for word in t.lower().split():
            h = int(hashlib.md5(word.strip(".,").encode()).hexdigest(), 16)
            out[i, h % rag.DIM] += 1
    return out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)


@pytest.fixture
def vector_db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    with psycopg.connect(url) as conn:
        available = conn.execute(
            "select 1 from pg_available_extensions where name = 'vector'"
        ).fetchone()
        if not available:
            pytest.skip("pgvector not installed on this Postgres")
        conn.execute("drop schema if exists rag cascade")
        conn.commit()
        yield conn


def test_ingest_and_search(vector_db, tmp_path, monkeypatch):
    monkeypatch.setattr(rag, "embed", fake_embed)
    monkeypatch.setattr(
        rag,
        "pages_with_pypdf",
        lambda data: [
            "Interconexiunea cu Republica Moldova a fost pusă în funcțiune în 2025. " * 3,
            "Investițiile în stații electrice au crescut față de anul anterior. " * 3,
        ],
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "doc-a.pdf").write_bytes(b"%PDF-fake")
    corpus = [{"id": "doc-a", "title": "Raport test", "year": 2025, "url": "https://x/a.pdf"}]

    assert rag.ingest(vector_db, str(tmp_path), corpus) == {
        "ingested": 1,
        "unchanged": 0,
        "chunks": 2,
    }
    assert rag.ingest(vector_db, str(tmp_path), corpus)["unchanged"] == 1

    hits = rag.search(vector_db, "investițiile în stații electrice", k=1)
    assert hits[0].page == 2 and hits[0].title == "Raport test"
