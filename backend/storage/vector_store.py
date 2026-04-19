"""
Vector search layer for semantic (meaning-based) document retrieval.

Backend priority:
  1. sentence-transformers (real semantic embeddings, ~80MB model)
  2. scikit-learn TF-IDF (lightweight, already in requirements, good for keyword matching)

Embeddings are stored in the SQLite DB as JSON blobs so no separate vector DB is needed.
The store is lazy — vectors are computed on first use and cached in memory.
"""
import json
import os
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────
# Backend detection
# ─────────────────────────────────────────────

SBERT_AVAILABLE = False
SKLEARN_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    SBERT_AVAILABLE = True
    print("[VEC] sentence-transformers available — using semantic embeddings")
except ImportError:
    pass

if not SBERT_AVAILABLE:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np
        SKLEARN_AVAILABLE = True
        print("[VEC] sentence-transformers not found — using TF-IDF semantic search")
    except ImportError:
        pass

VECTOR_AVAILABLE = SBERT_AVAILABLE or SKLEARN_AVAILABLE


class VectorStore:
    """Semantic search over indexed documents.

    Provides `semantic_search(query, limit)` which returns docs ranked by
    meaning-similarity rather than keyword overlap.
    """

    # Lightweight model: fast, 80MB, works offline
    SBERT_MODEL = "all-MiniLM-L6-v2"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._lock = threading.Lock()

        # In-memory caches
        self._doc_ids: List[int] = []
        self._doc_texts: List[str] = []
        self._embeddings = None          # np.ndarray when loaded
        self._tfidf_matrix = None        # sparse matrix for TF-IDF path
        self._dirty = True               # rebuild needed?

        # SBERT model (lazy-loaded)
        self._model = None

        # TF-IDF vectorizer
        self._tfidf = None

        self._ensure_schema()

    # ──────────────────────────────────────────
    # Schema
    # ──────────────────────────────────────────

    def _ensure_schema(self):
        """Add doc_embeddings table if not present."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS doc_embeddings (
                doc_id   INTEGER PRIMARY KEY,
                vector   TEXT NOT NULL,
                model    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    def semantic_search(self, query: str, limit: int = 5) -> List[Dict]:
        """Return top-N documents ranked by semantic similarity to query."""
        if not VECTOR_AVAILABLE:
            return []

        with self._lock:
            self._maybe_rebuild()

            if not self._doc_ids:
                return []

            if SBERT_AVAILABLE:
                return self._sbert_search(query, limit)
            else:
                return self._tfidf_search(query, limit)

    def mark_dirty(self):
        """Call after new docs are stored so the index rebuilds on next search."""
        with self._lock:
            self._dirty = True

    def index_doc(self, doc_id: int, content: str, title: str = "") -> bool:
        """Compute and store embedding for a single document."""
        if not VECTOR_AVAILABLE:
            return False
        text = f"{title} {content}"[:4096]
        try:
            if SBERT_AVAILABLE:
                model = self._get_model()
                vec = model.encode([text])[0].tolist()
                model_name = self.SBERT_MODEL
            else:
                # TF-IDF: store raw text, matrix built on search
                vec = []  # placeholder; text stored by _rebuild_tfidf
                model_name = "tfidf"

            from datetime import datetime
            self.conn.execute(
                """
                INSERT INTO doc_embeddings (doc_id, vector, model, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    vector = excluded.vector,
                    model  = excluded.model,
                    created_at = excluded.created_at
                """,
                (doc_id, json.dumps(vec), model_name, datetime.utcnow().isoformat()),
            )
            self.conn.commit()
            self._dirty = True
            return True
        except Exception as e:
            print(f"[VEC] index_doc failed: {e}")
            return False

    # ──────────────────────────────────────────
    # Internal — rebuild index
    # ──────────────────────────────────────────

    def _maybe_rebuild(self):
        if not self._dirty:
            return

        cursor = self.conn.cursor()
        rows = cursor.execute(
            "SELECT d.id, d.title, d.content FROM docs d ORDER BY d.id"
        ).fetchall()

        self._doc_ids = [r[0] for r in rows]
        self._doc_texts = [f"{r[1] or ''} {r[2] or ''}"[:4096] for r in rows]

        if SBERT_AVAILABLE and self._doc_texts:
            model = self._get_model()
            self._embeddings = model.encode(self._doc_texts, show_progress_bar=False)
        elif SKLEARN_AVAILABLE and self._doc_texts:
            self._rebuild_tfidf()

        self._dirty = False
        print(f"[VEC] Index rebuilt: {len(self._doc_ids)} docs")

    def _rebuild_tfidf(self):
        if not self._doc_texts:
            return
        self._tfidf = TfidfVectorizer(
            max_features=10000,
            ngram_range=(1, 2),
            stop_words="english",
            sublinear_tf=True,
        )
        self._tfidf_matrix = self._tfidf.fit_transform(self._doc_texts)

    def _get_model(self):
        if self._model is None:
            print(f"[VEC] Loading SBERT model: {self.SBERT_MODEL}")
            self._model = SentenceTransformer(self.SBERT_MODEL)
        return self._model

    # ──────────────────────────────────────────
    # Internal — search backends
    # ──────────────────────────────────────────

    def _sbert_search(self, query: str, limit: int) -> List[Dict]:
        model = self._get_model()
        q_vec = model.encode([query])
        # cosine similarity = dot product of normalised vectors
        sims = (self._embeddings @ q_vec.T).flatten()
        top_idx = sims.argsort()[::-1][:limit]
        return self._fetch_docs([self._doc_ids[i] for i in top_idx],
                                [float(sims[i]) for i in top_idx])

    def _tfidf_search(self, query: str, limit: int) -> List[Dict]:
        if self._tfidf is None or self._tfidf_matrix is None:
            return []
        q_vec = self._tfidf.transform([query])
        sims = cosine_similarity(q_vec, self._tfidf_matrix).flatten()
        top_idx = sims.argsort()[::-1][:limit]
        return self._fetch_docs([self._doc_ids[i] for i in top_idx],
                                [float(sims[i]) for i in top_idx])

    def _fetch_docs(self, doc_ids: List[int], scores: List[float]) -> List[Dict]:
        if not doc_ids:
            return []
        placeholders = ",".join("?" * len(doc_ids))
        cursor = self.conn.cursor()
        rows = cursor.execute(
            f"SELECT id, url, title, substr(content,1,400) AS snippet FROM docs WHERE id IN ({placeholders})",
            doc_ids,
        ).fetchall()
        # Preserve ranking order from scores
        id_to_row = {r[0]: r for r in rows}
        results = []
        for doc_id, score in zip(doc_ids, scores):
            if score < 0.05:  # filter near-zero similarity
                continue
            row = id_to_row.get(doc_id)
            if row:
                results.append({
                    "url": row[1],
                    "title": row[2],
                    "snippet": row[3],
                    "score": round(score, 4),
                    "source": "semantic",
                })
        return results


# ─────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────

_instance: Optional[VectorStore] = None
_instance_lock = threading.Lock()


def get_vector_store(conn: sqlite3.Connection) -> VectorStore:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = VectorStore(conn)
    return _instance
