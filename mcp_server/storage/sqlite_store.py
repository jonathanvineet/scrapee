"""
SQLite storage with FTS5 search, snippet highlighting, and in-process LRU cache.
"""

import sqlite3
import json
import time
import hashlib
import logging
import os
from typing import Optional
from mcp_server.logging_utils import setup_logging

logger = setup_logging(__name__)

CACHE_TTL = 300  # seconds — 5 minutes


class SQLiteStore:

    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.getenv("SQLITE_DB_PATH", "/tmp/scrapee.db")
        self._cache: dict = {}
        self._cache_ts: dict = {}
        self.conn = self._connect()
        self._init_schema()

    # ─── Connection ───────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS docs (
                id       TEXT PRIMARY KEY,
                url      TEXT UNIQUE NOT NULL,
                title    TEXT,
                content  TEXT,
                metadata TEXT,
                created_at INTEGER DEFAULT (strftime('%s','now'))
            );

            CREATE TABLE IF NOT EXISTS code_blocks (
                id       TEXT PRIMARY KEY,
                doc_id   TEXT REFERENCES docs(id),
                language TEXT,
                code     TEXT,
                context  TEXT,
                line_no  INTEGER
            );

            CREATE TABLE IF NOT EXISTS doc_topics (
                doc_id TEXT REFERENCES docs(id),
                topic  TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts
                USING fts5(title, content, content=docs, content_rowid=rowid);

            CREATE VIRTUAL TABLE IF NOT EXISTS code_fts
                USING fts5(code, context, content=code_blocks, content_rowid=rowid);

            CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
                INSERT INTO docs_fts(rowid, title, content)
                VALUES (new.rowid, new.title, new.content);
            END;

            CREATE TRIGGER IF NOT EXISTS code_ai AFTER INSERT ON code_blocks BEGIN
                INSERT INTO code_fts(rowid, code, context)
                VALUES (new.rowid, new.code, new.context);
            END;
        """)
        self.conn.commit()

    # ─── Cache helpers ────────────────────────────────────────────────────────

    def _cache_key(self, *parts) -> str:
        return hashlib.md5(":".join(str(p) for p in parts).encode()).hexdigest()

    def _cache_get(self, key: str):
        if key not in self._cache:
            return None
        if time.time() - self._cache_ts.get(key, 0) > CACHE_TTL:
            del self._cache[key]
            del self._cache_ts[key]
            return None
        return self._cache[key]

    def _cache_set(self, key: str, value):
        self._cache[key] = value
        self._cache_ts[key] = time.time()

    def _cache_invalidate(self):
        """Call after writes to clear stale search results."""
        self._cache.clear()
        self._cache_ts.clear()

    # ─── Write ────────────────────────────────────────────────────────────────

    def save_doc(self, doc_id: str, url: str, title: str, content: str, metadata: dict = None) -> bool:
        try:
            self.conn.execute("""
                INSERT INTO docs (id, url, title, content, metadata)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title    = excluded.title,
                    content  = excluded.content,
                    metadata = excluded.metadata
            """, (doc_id, url, title, content, json.dumps(metadata or {})))
            self.conn.commit()
            self._cache_invalidate()
            return True
        except Exception as e:
            logger.error(f"save_doc error: {e}")
            return False

    def save_code_block(self, block_id: str, doc_id: str, language: str,
                        code: str, context: str = "", line_no: int = 0) -> bool:
        try:
            self.conn.execute("""
                INSERT OR IGNORE INTO code_blocks (id, doc_id, language, code, context, line_no)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (block_id, doc_id, language, code, context, line_no))
            self.conn.commit()
            self._cache_invalidate()
            return True
        except Exception as e:
            logger.error(f"save_code_block error: {e}")
            return False

    # ─── Search ───────────────────────────────────────────────────────────────

    def search_with_snippets(self, query: str, limit: int = 5) -> list:
        """FTS5 search with highlighted snippets. Cached."""
        cache_key = self._cache_key("search", query, limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            rows = self.conn.execute("""
                SELECT
                    d.id,
                    d.url,
                    d.title,
                    snippet(docs_fts, 1, '[', ']', '...', 30) AS snippet,
                    rank
                FROM docs d
                JOIN docs_fts ON d.id = docs_fts.rowid
                WHERE docs_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit)).fetchall()
            result = [dict(r) for r in rows]
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"search_with_snippets error: {e}")
            return []

    def search_code_with_context(self, query: str, language: str = None, limit: int = 5) -> list:
        """FTS5 code search with optional language filter. Cached."""
        cache_key = self._cache_key("code", query, language, limit)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        try:
            if language:
                rows = self.conn.execute("""
                    SELECT
                        c.id, c.doc_id, c.language, c.code,
                        snippet(code_fts, 0, '[', ']', '...', 20) AS snippet,
                        d.url, d.title, rank
                    FROM code_blocks c
                    JOIN code_fts ON c.id = code_fts.rowid
                    JOIN docs d ON c.doc_id = d.id
                    WHERE code_fts MATCH ? AND c.language = ?
                    ORDER BY rank LIMIT ?
                """, (query, language, limit)).fetchall()
            else:
                rows = self.conn.execute("""
                    SELECT
                        c.id, c.doc_id, c.language, c.code,
                        snippet(code_fts, 0, '[', ']', '...', 20) AS snippet,
                        d.url, d.title, rank
                    FROM code_blocks c
                    JOIN code_fts ON c.id = code_fts.rowid
                    JOIN docs d ON c.doc_id = d.id
                    WHERE code_fts MATCH ?
                    ORDER BY rank LIMIT ?
                """, (query, limit)).fetchall()

            result = [dict(r) for r in rows]
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            logger.error(f"search_code_with_context error: {e}")
            return []

    # ─── Read ─────────────────────────────────────────────────────────────────

    def get_doc_by_id(self, doc_id: str) -> Optional[dict]:
        try:
            row = self.conn.execute(
                "SELECT * FROM docs WHERE id = ?", (doc_id,)
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def get_doc_by_url(self, url: str) -> Optional[dict]:
        try:
            row = self.conn.execute(
                "SELECT * FROM docs WHERE url = ?", (url,)
            ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None

    def list_docs(self, limit: int = 20) -> list:
        try:
            rows = self.conn.execute(
                "SELECT id, url, title, created_at FROM docs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"list_docs error: {e}")
            return []

    def get_stats(self) -> dict:
        try:
            doc_count  = self.conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            code_count = self.conn.execute("SELECT COUNT(*) FROM code_blocks").fetchone()[0]
            return {"total_docs": doc_count, "total_code_blocks": code_count}
        except Exception as e:
            return {"total_docs": 0, "total_code_blocks": 0, "error": str(e)}
