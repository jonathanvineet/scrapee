"""SQLite persistence and search index for docs and code resources."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from mcp_server.logging_utils import get_logger
from mcp_server.utils import code_uri_for_snippet, fts_query_from_text


logger = get_logger(__name__)


class SQLiteStore:
    """Persistent store with FTS indexes for documents and snippets."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_parent_dir(db_path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self._init_schema()
        logger.info("SQLite store initialized at %s", db_path)

    def _ensure_parent_dir(self, db_path: str) -> None:
        path = Path(db_path)
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)

    def _init_schema(self) -> None:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uri TEXT NOT NULL UNIQUE,
                    source_url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    scraped_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS document_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS code_snippets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    uri TEXT NOT NULL UNIQUE,
                    language TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    context TEXT NOT NULL,
                    line_start INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts
                USING fts5(uri, title, content, source_url, tokenize='porter unicode61');

                CREATE VIRTUAL TABLE IF NOT EXISTS code_fts
                USING fts5(uri, language, snippet, context, tokenize='porter unicode61');

                CREATE INDEX IF NOT EXISTS idx_documents_scraped_at ON documents(scraped_at DESC);
                CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_code_document_id ON code_snippets(document_id);
                CREATE INDEX IF NOT EXISTS idx_code_language ON code_snippets(language);
                """
            )
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def upsert_document(
        self,
        *,
        uri: str,
        source_url: str,
        title: str,
        content: str,
        metadata: Dict[str, object],
        chunks: List[str],
        code_blocks: List[Dict[str, object]],
    ) -> Dict[str, object]:
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id, scraped_at FROM documents WHERE uri = ? OR source_url = ?", (uri, source_url))
            existing = cursor.fetchone()
            if existing:
                doc_id = int(existing["id"])
                scraped_at = str(existing["scraped_at"])
                cursor.execute(
                    """
                    UPDATE documents
                    SET source_url = ?, title = ?, content = ?, metadata_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (source_url, title, content, json.dumps(metadata, ensure_ascii=False), now, doc_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO documents(uri, source_url, title, content, metadata_json, scraped_at, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uri, source_url, title, content, json.dumps(metadata, ensure_ascii=False), now, now),
                )
                doc_id = int(cursor.lastrowid)
                scraped_at = now

            cursor.execute("DELETE FROM docs_fts WHERE rowid = ?", (doc_id,))
            cursor.execute(
                "INSERT INTO docs_fts(rowid, uri, title, content, source_url) VALUES (?, ?, ?, ?, ?)",
                (doc_id, uri, title, content, source_url),
            )

            cursor.execute("DELETE FROM document_chunks WHERE document_id = ?", (doc_id,))
            for index, chunk in enumerate(chunks):
                cursor.execute(
                    "INSERT INTO document_chunks(document_id, chunk_index, chunk_text) VALUES (?, ?, ?)",
                    (doc_id, index, chunk),
                )

            old_code_ids = [
                int(row["id"]) for row in cursor.execute("SELECT id FROM code_snippets WHERE document_id = ?", (doc_id,))
            ]
            if old_code_ids:
                cursor.executemany("DELETE FROM code_fts WHERE rowid = ?", [(code_id,) for code_id in old_code_ids])
            cursor.execute("DELETE FROM code_snippets WHERE document_id = ?", (doc_id,))

            inserted_code_uris: List[str] = []
            for position, block in enumerate(code_blocks):
                snippet = str(block.get("snippet", "")).strip()
                if not snippet:
                    continue
                language = str(block.get("language", "text") or "text").lower()
                context = str(block.get("context", "") or "")
                line_start = int(block.get("line_start", 0) or 0)
                code_uri = code_uri_for_snippet(uri, position)
                cursor.execute(
                    """
                    INSERT INTO code_snippets(document_id, uri, language, snippet, context, line_start)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (doc_id, code_uri, language, snippet, context, line_start),
                )
                code_id = int(cursor.lastrowid)
                cursor.execute(
                    "INSERT INTO code_fts(rowid, uri, language, snippet, context) VALUES (?, ?, ?, ?, ?)",
                    (code_id, code_uri, language, snippet, context),
                )
                inserted_code_uris.append(code_uri)

            self.conn.commit()

        return {
            "document_id": doc_id,
            "uri": uri,
            "source_url": source_url,
            "title": title,
            "scraped_at": scraped_at,
            "updated_at": now,
            "code_uris": inserted_code_uris,
            "chunk_count": len(chunks),
        }

    def list_documents(self) -> List[Dict[str, object]]:
        cursor = self.conn.cursor()
        rows = cursor.execute(
            """
            SELECT uri, source_url, title, scraped_at, updated_at
            FROM documents
            ORDER BY scraped_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_code_resources(self) -> List[Dict[str, object]]:
        cursor = self.conn.cursor()
        rows = cursor.execute(
            """
            SELECT c.uri, c.language, d.uri AS document_uri, d.source_url
            FROM code_snippets c
            JOIN documents d ON d.id = c.document_id
            ORDER BY d.scraped_at DESC, c.id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_document_by_uri(self, uri: str) -> Optional[Dict[str, object]]:
        cursor = self.conn.cursor()
        row = cursor.execute(
            """
            SELECT id, uri, source_url, title, content, metadata_json, scraped_at, updated_at
            FROM documents
            WHERE uri = ?
            """,
            (uri,),
        ).fetchone()
        if not row:
            return None
        document = dict(row)
        document["metadata"] = json.loads(document.pop("metadata_json") or "{}")
        document["code_snippets"] = self.get_code_by_document_uri(uri)
        return document

    def get_document_by_source_url(self, source_url: str) -> Optional[Dict[str, object]]:
        cursor = self.conn.cursor()
        row = cursor.execute("SELECT uri FROM documents WHERE source_url = ?", (source_url,)).fetchone()
        if not row:
            return None
        return self.get_document_by_uri(str(row["uri"]))

    def get_code_by_uri(self, uri: str) -> Optional[Dict[str, object]]:
        cursor = self.conn.cursor()
        row = cursor.execute(
            """
            SELECT c.uri, c.language, c.snippet, c.context, c.line_start, d.uri AS document_uri, d.source_url, d.title
            FROM code_snippets c
            JOIN documents d ON d.id = c.document_id
            WHERE c.uri = ?
            """,
            (uri,),
        ).fetchone()
        return dict(row) if row else None

    def get_code_by_document_uri(self, document_uri: str) -> List[Dict[str, object]]:
        cursor = self.conn.cursor()
        rows = cursor.execute(
            """
            SELECT c.uri, c.language, c.snippet, c.context, c.line_start
            FROM code_snippets c
            JOIN documents d ON d.id = c.document_id
            WHERE d.uri = ?
            ORDER BY c.id ASC
            """,
            (document_uri,),
        ).fetchall()
        return [dict(row) for row in rows]

    def search_documents(self, query: str, limit: int) -> List[Dict[str, object]]:
        cursor = self.conn.cursor()
        prepared = fts_query_from_text(query)
        try:
            rows = cursor.execute(
                """
                SELECT d.uri, d.source_url, d.title,
                       snippet(docs_fts, 2, '[', ']', '...', 24) AS snippet,
                       bm25(docs_fts) AS score
                FROM docs_fts
                JOIN documents d ON d.id = docs_fts.rowid
                WHERE docs_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (prepared, limit),
            ).fetchall()
            results = [dict(row) for row in rows]
        except sqlite3.OperationalError:
            like = f"%{query}%"
            rows = cursor.execute(
                """
                SELECT uri, source_url, title, substr(content, 1, 240) AS snippet, 0.0 AS score
                FROM documents
                WHERE title LIKE ? OR content LIKE ?
                ORDER BY scraped_at DESC
                LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()
            results = [dict(row) for row in rows]
        return results

    def search_code(self, query: str, limit: int, language: str | None = None) -> List[Dict[str, object]]:
        cursor = self.conn.cursor()
        prepared = fts_query_from_text(query)
        filters: List[object] = [prepared]
        sql = """
            SELECT c.uri, c.language, d.uri AS document_uri, d.source_url, d.title,
                   snippet(code_fts, 2, '[', ']', '...', 20) AS snippet,
                   c.context, bm25(code_fts) AS score
            FROM code_fts
            JOIN code_snippets c ON c.id = code_fts.rowid
            JOIN documents d ON d.id = c.document_id
            WHERE code_fts MATCH ?
        """
        if language:
            sql += " AND c.language = ?"
            filters.append(language.lower())
        sql += " ORDER BY score LIMIT ?"
        filters.append(limit)
        try:
            rows = cursor.execute(sql, tuple(filters)).fetchall()
            results = [dict(row) for row in rows]
        except sqlite3.OperationalError:
            like = f"%{query}%"
            fallback_sql = """
                SELECT c.uri, c.language, d.uri AS document_uri, d.source_url, d.title,
                       substr(c.snippet, 1, 220) AS snippet, c.context, 0.0 AS score
                FROM code_snippets c
                JOIN documents d ON d.id = c.document_id
                WHERE (c.snippet LIKE ? OR c.context LIKE ?)
            """
            fallback_filters: List[object] = [like, like]
            if language:
                fallback_sql += " AND c.language = ?"
                fallback_filters.append(language.lower())
            fallback_sql += " ORDER BY c.id DESC LIMIT ?"
            fallback_filters.append(limit)
            rows = cursor.execute(fallback_sql, tuple(fallback_filters)).fetchall()
            results = [dict(row) for row in rows]
        return results

    def stats(self) -> Dict[str, object]:
        cursor = self.conn.cursor()
        total_docs = int(cursor.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"])
        total_code = int(cursor.execute("SELECT COUNT(*) AS count FROM code_snippets").fetchone()["count"])
        total_chunks = int(cursor.execute("SELECT COUNT(*) AS count FROM document_chunks").fetchone()["count"])
        return {
            "total_documents": total_docs,
            "total_code_snippets": total_code,
            "total_chunks": total_chunks,
            "database_path": self.db_path,
        }
