"""SQLite-backed storage and FTS5 search for the MCP server."""
import json
import os
import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional


def _running_on_vercel() -> bool:
    return bool(
        os.getenv("VERCEL")
        or os.getenv("VERCEL_ENV")
        or os.getenv("NOW_REGION")
        or os.getenv("VERCEL_REGION")
    )


def _default_db_path() -> str:
    override = os.getenv("SCRAPEE_SQLITE_PATH") or os.getenv("SQLITE_DB_PATH")
    if override:
        return override

    if _running_on_vercel():
        return os.path.join("/tmp", "scrapee", "docs.db")

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(backend_dir, "db", "docs.db")


def _ensure_parent_dir(db_path: str) -> None:
    if not db_path or db_path == ":memory:":
        return
    if db_path.startswith("file:"):
        return
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


class SQLiteStore:
    """SQLite-backed storage for documents, topics, and code blocks."""
    
    def __init__(self, db_path: str = None):
        """
        Initialize SQLite storage.
        
        Args:
            db_path: Path to SQLite database file (default: backend/db/docs.db)
        """
        self.db_path = db_path or _default_db_path()
        _ensure_parent_dir(self.db_path)

        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        except sqlite3.OperationalError:
            fallback_path = os.path.join("/tmp", "scrapee", "docs.db")
            if self.db_path != fallback_path:
                self.db_path = fallback_path
                _ensure_parent_dir(self.db_path)
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            else:
                self.db_path = ":memory:"
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)

        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.db_path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self._init_schema()
        print(f"✓ SQLite initialized: {self.db_path}")
    
    def _init_schema(self):
        """Create or migrate the schema to the rowid-backed FTS layout."""
        if self._needs_migration():
            self._migrate_legacy_schema()
        self._create_schema()

    def _create_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS docs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT,
                content TEXT,
                domain TEXT,
                language TEXT,
                scraped_at TEXT,
                metadata TEXT
            );

            CREATE TABLE IF NOT EXISTS code_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                snippet TEXT,
                language TEXT,
                context TEXT,
                line_number INTEGER,
                FOREIGN KEY (doc_id) REFERENCES docs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS doc_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                topic TEXT,
                heading TEXT,
                level INTEGER,
                content TEXT,
                FOREIGN KEY (doc_id) REFERENCES docs(id) ON DELETE CASCADE
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts
            USING fts5(title, content, url UNINDEXED, tokenize='porter unicode61');

            CREATE VIRTUAL TABLE IF NOT EXISTS code_fts
            USING fts5(snippet, context, language, url UNINDEXED, title UNINDEXED, tokenize='porter unicode61');

            CREATE INDEX IF NOT EXISTS idx_docs_url ON docs(url);
            CREATE INDEX IF NOT EXISTS idx_docs_domain ON docs(domain);
            CREATE INDEX IF NOT EXISTS idx_docs_scraped_at ON docs(scraped_at DESC);
            CREATE INDEX IF NOT EXISTS idx_code_doc_id ON code_blocks(doc_id);
            CREATE INDEX IF NOT EXISTS idx_code_language ON code_blocks(language);
            CREATE INDEX IF NOT EXISTS idx_topics_doc_id ON doc_topics(doc_id);
            """
        )
        self.conn.commit()

    def _needs_migration(self) -> bool:
        if not self._table_exists("docs"):
            return False
        docs_columns = self._table_columns("docs")
        code_columns = self._table_columns("code_blocks") if self._table_exists("code_blocks") else []
        topic_columns = self._table_columns("doc_topics") if self._table_exists("doc_topics") else []
        return "id" not in docs_columns or (code_columns and "doc_id" not in code_columns) or (topic_columns and "doc_id" not in topic_columns)

    def _migrate_legacy_schema(self) -> None:
        cursor = self.conn.cursor()
        legacy_docs = [dict(row) for row in cursor.execute("SELECT * FROM docs").fetchall()] if self._table_exists("docs") else []
        legacy_code = [dict(row) for row in cursor.execute("SELECT * FROM code_blocks").fetchall()] if self._table_exists("code_blocks") else []
        legacy_topics = [dict(row) for row in cursor.execute("SELECT * FROM doc_topics").fetchall()] if self._table_exists("doc_topics") else []

        cursor.executescript(
            """
            DROP TABLE IF EXISTS docs_fts;
            DROP TABLE IF EXISTS code_fts;
            DROP TABLE IF EXISTS doc_topics;
            DROP TABLE IF EXISTS code_blocks;
            DROP TABLE IF EXISTS docs;
            """
        )
        self.conn.commit()
        self._create_schema()

        code_by_url: Dict[str, List[Dict]] = {}
        for block in legacy_code:
            block_url = block.get("url")
            if not block_url:
                continue
            code_by_url.setdefault(block_url, []).append(
                {
                    "snippet": block.get("snippet", ""),
                    "language": block.get("language", ""),
                    "context": block.get("context", ""),
                    "line_number": block.get("line_number", 0),
                }
            )

        topics_by_url: Dict[str, List[Dict]] = {}
        for topic in legacy_topics:
            topic_url = topic.get("url")
            if not topic_url:
                continue
            topics_by_url.setdefault(topic_url, []).append(
                {
                    "topic": topic.get("topic", ""),
                    "heading": topic.get("heading", ""),
                    "level": topic.get("level", 0),
                    "content": topic.get("content", ""),
                }
            )

        for doc in legacy_docs:
            metadata = self._load_metadata(doc.get("metadata"))
            if doc.get("title") and not metadata.get("title"):
                metadata["title"] = doc.get("title")
            if doc.get("language") and not metadata.get("language"):
                metadata["language"] = doc.get("language")
            self.save_doc(
                doc.get("url", ""),
                doc.get("content", ""),
                metadata=metadata,
                code_blocks=code_by_url.get(doc.get("url", ""), []),
                topics=topics_by_url.get(doc.get("url", ""), []),
            )

    def _table_exists(self, table_name: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (table_name,))
        return cursor.fetchone() is not None

    def _table_columns(self, table_name: str) -> List[str]:
        cursor = self.conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        return [row[1] for row in cursor.fetchall()]
    
    def save_doc(
        self, 
        url: str, 
        content: str, 
        metadata: Optional[Dict] = None,
        code_blocks: Optional[List[Dict]] = None,
        topics: Optional[List[Dict]] = None
    ) -> bool:
        """
        Save document with structured data.
        
        Args:
            url: Document URL
            content: Full text content
            metadata: Dict with title, language, domain, etc.
            code_blocks: List of dicts with snippet, language, context
            topics: List of dicts with topic, heading, level, content
        
        Returns:
            True if successful
        """
        try:
            metadata = metadata or {}
            title = metadata.get("title", "")
            domain = self._extract_domain(url)
            language = metadata.get("language", "")
            scraped_at = datetime.utcnow().isoformat()
            
            cursor = self.conn.cursor()
            cursor.execute("SELECT id FROM docs WHERE url = ?", (url,))
            existing = cursor.fetchone()

            if existing:
                doc_id = existing["id"]
                cursor.execute(
                    """
                    UPDATE docs
                    SET title = ?, content = ?, domain = ?, language = ?, scraped_at = ?, metadata = ?
                    WHERE id = ?
                    """,
                    (title, content, domain, language, scraped_at, json.dumps(metadata), doc_id),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO docs (url, title, content, domain, language, scraped_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (url, title, content, domain, language, scraped_at, json.dumps(metadata)),
                )
                doc_id = cursor.lastrowid

            cursor.execute("DELETE FROM docs_fts WHERE rowid = ?", (doc_id,))
            cursor.execute(
                "INSERT INTO docs_fts(rowid, title, content, url) VALUES (?, ?, ?, ?)",
                (doc_id, title, content, url),
            )

            old_code_ids = [row["id"] for row in cursor.execute("SELECT id FROM code_blocks WHERE doc_id = ?", (doc_id,)).fetchall()]
            if old_code_ids:
                cursor.executemany("DELETE FROM code_fts WHERE rowid = ?", [(code_id,) for code_id in old_code_ids])
            cursor.execute("DELETE FROM code_blocks WHERE doc_id = ?", (doc_id,))

            for block in self._dedupe_code_blocks(code_blocks or []):
                cursor.execute(
                    """
                    INSERT INTO code_blocks (doc_id, snippet, language, context, line_number)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        block.get("snippet", ""),
                        block.get("language", ""),
                        block.get("context", ""),
                        block.get("line_number", 0),
                    ),
                )
                block_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO code_fts(rowid, snippet, context, language, url, title) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        block_id,
                        block.get("snippet", ""),
                        block.get("context", ""),
                        block.get("language", ""),
                        url,
                        title,
                    ),
                )

            cursor.execute("DELETE FROM doc_topics WHERE doc_id = ?", (doc_id,))
            for topic in self._dedupe_topics(topics or []):
                cursor.execute(
                    """
                    INSERT INTO doc_topics (doc_id, topic, heading, level, content)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        topic.get("topic", ""),
                        topic.get("heading", ""),
                        topic.get("level", 0),
                        topic.get("content", ""),
                    ),
                )
            
            self.conn.commit()
            return True
            
        except Exception as e:
            print(f"Error saving doc {url}: {e}")
            self.conn.rollback()
            return False
    
    def get_doc(self, url: str) -> Optional[Dict]:
        """
        Retrieve document by URL.
        
        Returns:
            Dict with url, title, content, metadata or None
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, url, title, content, domain, language, scraped_at, metadata
            FROM docs WHERE url = ?
        """, (url,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        doc = {
            "id": row["id"],
            "url": row["url"],
            "title": row["title"],
            "content": row["content"],
            "domain": row["domain"],
            "language": row["language"],
            "scraped_at": row["scraped_at"],
            "metadata": self._load_metadata(row["metadata"]),
        }
        doc["topics"] = self.get_topics_by_url(url)
        doc["code_blocks"] = self.get_code_blocks_by_url(url)
        return doc
    
    def list_docs(self, limit: Optional[int] = None) -> List[str]:
        """
        List all document URLs.
        
        Returns:
            List of URLs
        """
        cursor = self.conn.cursor()
        if limit is None:
            cursor.execute("SELECT url FROM docs ORDER BY scraped_at DESC")
        else:
            cursor.execute("SELECT url FROM docs ORDER BY scraped_at DESC LIMIT ?", (limit,))
        return [row["url"] for row in cursor.fetchall()]
    
    def get_doc_summaries(self, limit: int = 25) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT url, title, domain, scraped_at
            FROM docs
            ORDER BY scraped_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def search_docs(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Full-text search in documents.
        
        Args:
            query: Search query
            limit: Maximum results
        
        Returns:
            List of dicts with url, title, snippet, rank
        """
        cursor = self.conn.cursor()
        prepared_query = self._prepare_fts_query(query)
        cursor.execute(
            """
            SELECT
                d.id,
                d.url,
                d.title,
                snippet(docs_fts, 1, '[', ']', '...', 32) AS snippet,
                bm25(docs_fts) AS score
            FROM docs_fts
            JOIN docs d ON docs_fts.rowid = d.id
            WHERE docs_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (prepared_query, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def search_and_get(self, query: str, limit: int = 5, snippet_length: int = 400) -> List[Dict]:
        results = self.search_docs(query, limit=limit)
        payload = []
        for row in results:
            snippet = row.get("snippet") or ""
            if len(snippet) > snippet_length:
                snippet = snippet[:snippet_length].rstrip() + "..."
            payload.append(
                {
                    "url": row.get("url", ""),
                    "title": row.get("title", "") or row.get("url", ""),
                    "snippet": snippet,
                    "score": row.get("score", 0.0),
                }
            )
        return payload
    
    def search_code(self, query: str, language: str = None, limit: int = 10) -> List[Dict]:
        """
        Search code blocks.
        
        Args:
            query: Search query
            language: Optional language filter
            limit: Maximum results
        
        Returns:
            List of dicts with snippet, language, context, url
        """
        cursor = self.conn.cursor()
        prepared_query = self._prepare_fts_query(query)
        if language:
            cursor.execute(
                """
                SELECT
                    d.url,
                    d.title,
                    c.snippet,
                    c.language,
                    c.context,
                    snippet(code_fts, 0, '[', ']', '...', 24) AS highlighted,
                    bm25(code_fts) AS score
                FROM code_fts
                JOIN code_blocks c ON code_fts.rowid = c.id
                JOIN docs d ON c.doc_id = d.id
                WHERE code_fts MATCH ? AND c.language = ?
                ORDER BY score
                LIMIT ?
                """,
                (prepared_query, language, limit),
            )
        else:
            cursor.execute(
                """
                SELECT
                    d.url,
                    d.title,
                    c.snippet,
                    c.language,
                    c.context,
                    snippet(code_fts, 0, '[', ']', '...', 24) AS highlighted,
                    bm25(code_fts) AS score
                FROM code_fts
                JOIN code_blocks c ON code_fts.rowid = c.id
                JOIN docs d ON c.doc_id = d.id
                WHERE code_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (prepared_query, limit),
            )
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_code_examples(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Get code examples matching query.
        
        Args:
            query: Search query
            limit: Maximum results
        
        Returns:
            List of code examples with context
        """
        return self.search_code(query, limit=limit)
    
    def get_docs_by_domain(self, domain: str) -> List[Dict]:
        """
        Get all documents from a specific domain.
        
        Args:
            domain: Domain name (e.g., 'docs.hedera.com')
        
        Returns:
            List of document dicts
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT url, title, scraped_at
            FROM docs
            WHERE domain = ?
            ORDER BY scraped_at DESC
            """,
            (domain,),
        )
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_topics_by_url(self, url: str) -> List[Dict]:
        """
        Get document structure/topics by URL.
        
        Args:
            url: Document URL
        
        Returns:
            List of topics/headings
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT t.topic, t.heading, t.level, t.content
            FROM doc_topics t
            JOIN docs d ON t.doc_id = d.id
            WHERE d.url = ?
            ORDER BY t.id
            """,
            (url,),
        )
        
        return [dict(row) for row in cursor.fetchall()]

    def get_code_blocks_by_url(self, url: str, limit: int = 50) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT c.snippet, c.language, c.context, c.line_number
            FROM code_blocks c
            JOIN docs d ON c.doc_id = d.id
            WHERE d.url = ?
            ORDER BY c.id
            LIMIT ?
            """,
            (url, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def list_domains(self) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT domain, COUNT(*) AS count
            FROM docs
            GROUP BY domain
            ORDER BY count DESC, domain ASC
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict:
        """
        Get storage statistics.
        
        Returns:
            Dict with counts and info
        """
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) as count FROM docs")
        doc_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(*) as count FROM code_blocks")
        code_count = cursor.fetchone()["count"]

        cursor.execute("SELECT COUNT(DISTINCT domain) as count FROM docs")
        domain_count = cursor.fetchone()["count"]

        cursor.execute("SELECT domain, COUNT(*) as count FROM docs GROUP BY domain ORDER BY count DESC LIMIT 5")
        top_domains = [dict(row) for row in cursor.fetchall()]
        sqlite_ok = False
        try:
            cursor.execute("SELECT 1")
            sqlite_ok = cursor.fetchone()[0] == 1
        except sqlite3.Error:
            sqlite_ok = False
        
        return {
            "total_docs": doc_count,
            "total_code_blocks": code_count,
            "total_domains": domain_count,
            "top_domains": top_domains,
            "sqlite_ok": sqlite_ok,
            "db_path": self.db_path,
        }

    def _prepare_fts_query(self, query: str) -> str:
        tokens = [token for token in re.findall(r"[A-Za-z0-9_./:-]+", query) if token]
        if not tokens:
            return '""'
        return " AND ".join(f'"{token}"*' for token in tokens)

    def _load_metadata(self, raw_metadata) -> Dict:
        if not raw_metadata:
            return {}
        if isinstance(raw_metadata, dict):
            return raw_metadata
        try:
            return json.loads(raw_metadata)
        except (TypeError, json.JSONDecodeError):
            return {}

    def _dedupe_code_blocks(self, code_blocks: List[Dict]) -> List[Dict]:
        seen = set()
        unique_blocks = []
        for block in code_blocks:
            snippet = (block.get("snippet") or "").strip()
            if not snippet:
                continue
            fingerprint = (snippet, (block.get("language") or "").strip(), (block.get("context") or "").strip())
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique_blocks.append(
                {
                    "snippet": snippet,
                    "language": (block.get("language") or "unknown").strip(),
                    "context": (block.get("context") or "").strip(),
                    "line_number": int(block.get("line_number") or 0),
                }
            )
        return unique_blocks

    def _dedupe_topics(self, topics: List[Dict]) -> List[Dict]:
        seen = set()
        unique_topics = []
        for topic in topics:
            key = ((topic.get("topic") or "").strip(), (topic.get("heading") or "").strip())
            if not any(key) or key in seen:
                continue
            seen.add(key)
            unique_topics.append(
                {
                    "topic": key[0],
                    "heading": key[1],
                    "level": int(topic.get("level") or 0),
                    "content": (topic.get("content") or "").strip(),
                }
            )
        return unique_topics
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc or ""
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


# Singleton instance
_sqlite_store = None


def get_sqlite_store(db_path: str = None) -> SQLiteStore:
    """
    Get singleton SQLite store instance.
    
    Args:
        db_path: Optional custom database path
    
    Returns:
        SQLiteStore instance
    """
    global _sqlite_store
    if _sqlite_store is None:
        _sqlite_store = SQLiteStore(db_path)
    return _sqlite_store
