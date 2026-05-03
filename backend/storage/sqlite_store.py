"""SQLite-backed storage and FTS5 search for the MCP server."""
import json
import os
import re
import sqlite3
import threading
from datetime import datetime
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    from storage.vector_store import get_vector_store, VECTOR_AVAILABLE
except Exception:
    get_vector_store = None
    VECTOR_AVAILABLE = False


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
        
        self.redis_client = None
        self._sync_lock = threading.Lock()
        
        # Initialize Redis if configured
        if REDIS_AVAILABLE:
            redis_url = os.getenv("REDIS_URL") or os.getenv("KV_URL")
            if redis_url:
                try:
                    self.redis_client = redis.from_url(redis_url, socket_timeout=5)
                    self.redis_client.ping()
                    print("✓ Redis connected for SQLite persistence")
                except Exception as e:
                    print(f"⚠ Redis connection failed: {e}")
                    self.redis_client = None
        
        # Attempt to pull remote DB before opening Local SQLite
        self._pull_from_redis()

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

    def _pull_from_redis(self):
        """Download the SQLite database from Redis to the local filesystem."""
        if not self.redis_client or self.db_path == ":memory:":
            return
        
        try:
            data = self.redis_client.get("scrapee:sqlite:db")
            if data:
                with open(self.db_path, "wb") as f:
                    f.write(data)
                print(f"✓ Pulled SQLite database from Redis ({len(data)} bytes)")
            else:
                print("ℹ No existing SQLite database found in Redis")
        except Exception as e:
            print(f"⚠ Failed to pull DB from Redis: {e}")

    def _push_to_redis(self):
        """
        Upload the current SQLite database to Redis.
        
        VERCEL-SAFE: NO THREADING
        - Direct synchronous call
        - Never creates background threads (they die on Vercel)
        - Executes inline during response handling
        - Fast enough (<500ms) for Vercel
        """
        if not self.redis_client or self.db_path == ":memory:":
            return
        
        # SYNCHRONOUS (not threaded - threading is unsafe on Vercel)
        with self._sync_lock:
            try:
                with open(self.db_path, "rb") as f:
                    data = f.read()
                self.redis_client.set("scrapee:sqlite:db", data, ex=86400)  # 24h TTL
                print(f"✓ Pushed SQLite DB to Redis ({len(data)} bytes)")
            except Exception as e:
                print(f"⚠ Failed to push DB to Redis: {e}")

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
                metadata TEXT,
                score REAL DEFAULT 1.0
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

            CREATE TABLE IF NOT EXISTS query_source_map (
                query TEXT NOT NULL,
                url TEXT NOT NULL,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                PRIMARY KEY (query, url)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts
            USING fts5(title, content, url UNINDEXED, tokenize='porter unicode61');

            CREATE VIRTUAL TABLE IF NOT EXISTS code_fts
            USING fts5(snippet, context, language, url UNINDEXED, title UNINDEXED, tokenize='porter unicode61');

            CREATE INDEX IF NOT EXISTS idx_docs_url ON docs(url);
            CREATE INDEX IF NOT EXISTS idx_docs_domain ON docs(domain);
            CREATE INDEX IF NOT EXISTS idx_docs_scraped_at ON docs(scraped_at DESC);
            CREATE INDEX IF NOT EXISTS idx_docs_score ON docs(score DESC);
            CREATE INDEX IF NOT EXISTS idx_code_doc_id ON code_blocks(doc_id);
            CREATE INDEX IF NOT EXISTS idx_code_language ON code_blocks(language);
            CREATE INDEX IF NOT EXISTS idx_topics_doc_id ON doc_topics(doc_id);

            CREATE TABLE IF NOT EXISTS scrape_jobs (
                query TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_scrape_jobs_status ON scrape_jobs(status);
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
        
        REDIS PERSISTENCE:
        - Saves to SQLite for fast local search
        - Also saves to Redis (24h TTL) for persistence across Vercel cold starts
        - Next query retrieves from Redis if available
        
        Args:
            url: Document URL
            content: Full text content
            metadata: Dict with title, language, domain, etc.
            code_blocks: List of dicts with snippet, language, context
            topics: List of dicts with topic, heading, level, content
        
        Returns:
            True if successful, False if skipped or error
        """
        metadata = metadata or {}

        # � CRITICAL NORMALIZATION
        content = (content or "").lower().strip()
        
        # 🚨 HARD VALIDATION — skip low-quality content
        if len(content) < 50:
            print(f"[SKIP] Low-quality content ({len(content)} chars): {url}")
            return False

        if not code_blocks and len(content.split()) < 20:
            print(f"[SKIP] No useful data: {url}")
            return False

        try:
            title = metadata.get("title", "")
            domain = self._extract_domain(url)
            language = metadata.get("language", "")
            scraped_at = datetime.utcnow().isoformat()
            
            cursor = self.conn.cursor()

            # ✅ DEBUG: Log content extraction success
            print(f"[SAVE] Processing: {url}")
            print(f"[SAVE] Content length: {len(content)} chars | Words: {len(content.split())}")

            # Content-level deduplication: skip if identical content already stored (different URL)
            content_fingerprint = content[:500]
            cursor.execute(
                "SELECT id FROM docs WHERE content LIKE ? AND url != ?",
                (content_fingerprint + "%", url),
            )
            if cursor.fetchone():
                print(f"[SKIP] Duplicate content already stored: {url}")
                return False

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

            # FTS index
            cursor.execute("DELETE FROM docs_fts WHERE rowid = ?", (doc_id,))
            cursor.execute(
                "INSERT INTO docs_fts(rowid, title, content, url) VALUES (?, ?, ?, ?)",
                (doc_id, title, content, url),
            )

            old_code_ids = [row["id"] for row in cursor.execute("SELECT id FROM code_blocks WHERE doc_id = ?", (doc_id,)).fetchall()]
            if old_code_ids:
                cursor.executemany("DELETE FROM code_fts WHERE rowid = ?", [(code_id,) for code_id in old_code_ids])
            cursor.execute("DELETE FROM code_blocks WHERE doc_id = ?", (doc_id,))

            dedupe_blocks = self._dedupe_code_blocks(code_blocks or [])
            
            for block in dedupe_blocks:
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
            print(f"[SAVE] Stored: {url} ({len(content)} chars)")
            
            # Level 2 Semantic Vector Indexing
            if VECTOR_AVAILABLE and get_vector_store:
                try:
                    vs = get_vector_store(self.conn)
                    vs.index_doc(doc_id, content, title)
                except Exception as e:
                    print(f"[VEC] Error indexing doc {doc_id}: {e}")
            
            # 📦 REDIS CACHE: Store doc in Redis for fast retrieval across cold starts
            try:
                doc_cache = {
                    "id": doc_id,
                    "url": url,
                    "title": title,
                    "content": content,
                    "domain": domain,
                    "language": language,
                    "scraped_at": scraped_at,
                    "metadata": metadata
                }
                if self.redis_client:
                    self.redis_client.set(
                        f"doc:{url}",
                        json.dumps(doc_cache),
                        ex=86400  # 24-hour TTL
                    )
            except Exception as e:
                print(f"⚠ Failed to cache doc in Redis: {e}")
            
            # Persist to Redis
            self._push_to_redis()
            return True
            
        except Exception as e:
            print(f"Error saving doc {url}: {e}")
            self.conn.rollback()
            return False
    
    def get_doc(self, url: str) -> Optional[Dict]:
        """
        Retrieve document by URL.
        
        REDIS READ-THROUGH:
        - Checks Redis first (fast, survives cold starts)
        - Falls back to SQLite if not in Redis
        - Re-caches in Redis on SQLite hit
        
        Returns:
            Dict with url, title, content, metadata or None
        """
        # ✅ REDIS READ-THROUGH: Check Redis first
        if self.redis_client:
            try:
                cached = self.redis_client.get(f"doc:{url}")
                if cached:
                    doc_data = json.loads(cached)
                    # Fetch related data from SQLite (topics, code blocks)
                    doc_data["topics"] = self.get_topics_by_url(url)
                    doc_data["code_blocks"] = self.get_code_blocks_by_url(url)
                    return doc_data
            except Exception as e:
                print(f"⚠ Redis read-through error: {e}")
        
        # 📚 Fallback to SQLite
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
        
        # 📦 RE-CACHE in Redis for next cold start
        try:
            if self.redis_client:
                self.redis_client.set(
                    f"doc:{url}",
                    json.dumps({
                        "id": doc["id"],
                        "url": doc["url"],
                        "title": doc["title"],
                        "content": doc["content"],
                        "domain": doc["domain"],
                        "language": doc["language"],
                        "scraped_at": doc["scraped_at"],
                        "metadata": doc["metadata"]
                    }),
                    ex=86400  # 24-hour TTL
                )
        except Exception as e:
            print(f"⚠ Failed to re-cache doc in Redis: {e}")
        
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
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein distance between two strings (typo-tolerant)."""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)
        
        prev_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row
        return prev_row[-1]
    
    def _fuzzy_match(self, query: str, target: str, max_distance: int = 2) -> Tuple[bool, float]:
        """
        Fuzzy match with typo tolerance.
        
        Returns:
            (is_match, similarity_score) where similarity_score is 0-1
        """
        distance = self._levenshtein_distance(query.lower(), target.lower())
        is_match = distance <= max_distance
        similarity = 1.0 - (distance / max(len(query), len(target)))
        return is_match, similarity
    
    def _fuzzy_search_tokens(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Fallback fuzzy search: tokenize query and find close matches in database.
        Handles typos like 'devopssct' -> 'devopsct'.
        
        Returns:
            List of matching documents sorted by similarity
        """
        tokens = query.lower().split()
        if not tokens:
            return []
        
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, url, title, content FROM docs")
        all_docs = [dict(row) for row in cursor.fetchall()]
        
        scored_results = []
        for doc in all_docs:
            doc_text = f"{doc['title']} {doc['content']}".lower()
            doc_tokens = doc_text.split()
            
            # Score based on fuzzy matches of query tokens
            total_score = 0.0
            matched_tokens = 0
            
            for qt in tokens:
                best_match_score = 0.0
                for dt in doc_tokens:
                    is_match, similarity = self._fuzzy_match(qt, dt, max_distance=2)
                    if is_match and similarity > best_match_score:
                        best_match_score = similarity
                
                if best_match_score > 0:
                    total_score += best_match_score
                    matched_tokens += 1
            
            # Only include docs that match at least one token
            if matched_tokens > 0:
                avg_score = total_score / len(tokens)
                scored_results.append({
                    'id': doc['id'],
                    'url': doc['url'],
                    'title': doc['title'],
                    'snippet': doc['content'][:200] + "..." if len(doc['content']) > 200 else doc['content'],
                    'score': avg_score
                })
        
        # Sort by score descending
        scored_results.sort(key=lambda x: x['score'], reverse=True)
        return scored_results[:limit]
    
    def search_docs(self, query: str, limit: int = 10) -> List[Dict]:
        """🔥 RULE 3: 3-tier search fallback — NEVER RETURN EMPTY.
        
        Tier 1: FTS with expansion (fast, precise)
        Tier 2: LIKE fallback (comprehensive)
        Tier 3: Recent docs (last resort, always returns something)
        """
        query = query.lower()
        cursor = self.conn.cursor()
        
        # TIER 1: FTS with expansion (word* wildcard)
        fts_query = " OR ".join([f"{w}*" for w in query.split()])
        print(f"[SEARCH] T1-FTS: {fts_query!r}")
        
        try:
            cursor.execute(
                """
                SELECT d.id, d.url, d.title,
                       snippet(docs_fts, 1, '[', ']', '...', 32) AS snippet,
                       bm25(docs_fts) AS fts_score,
                       d.score AS learned_score
                FROM docs_fts
                JOIN docs d ON docs_fts.rowid = d.id
                WHERE docs_fts MATCH ?
                LIMIT ?
                """,
                (fts_query, limit),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            print(f"[SEARCH] T1-FTS found {len(rows)}")

            results = []
            for r in rows:
                fts = float(r.get("fts_score") or 0.0)
                learned = float(r.get("learned_score") or 1.0)
                # Combine scores: learned score + inverted fts similarity
                combined = learned + (1.0 / (fts + 1.0))
                # Query-source affinity boost
                try:
                    affinity = self.get_query_source_affinity(query, r.get("url"))
                    if affinity > 0:
                        combined += 0.5
                except Exception:
                    pass

                r["final_score"] = combined
                results.append(r)

            # Sort by combined score descending
            results.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)

            if results:
                return results
        except Exception as e:
            print(f"[SEARCH] T1-FTS failed: {e}")
        
        # TIER 2: LIKE fallback (always runs)
        like_query = f"%{query}%"
        print(f"[SEARCH] T2-LIKE: {like_query!r}")
        
        cursor.execute(
            """
            SELECT id, url, title, substr(content, 1, 300) AS snippet, score AS learned_score
            FROM docs
            WHERE content LIKE ?
            LIMIT ?
            """,
            (like_query, limit),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        print(f"[SEARCH] T2-LIKE found {len(rows)}")

        if rows:
            results = []
            for r in rows:
                learned = float(r.get("learned_score") or 1.0)
                # LIKE fallback has no fts_score; use learned as primary
                combined = learned
                try:
                    affinity = self.get_query_source_affinity(query, r.get("url"))
                    if affinity > 0:
                        combined += 0.5
                except Exception:
                    pass
                r["final_score"] = combined
                results.append(r)

            results.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
            return results
        
        # TIER 3: Last resort — recent docs (ALWAYS returns something)
        print(f"[SEARCH] T3-RECENT fallback")
        cursor.execute(
            """
            SELECT id, url, title, substr(content, 1, 300) AS snippet, score AS learned_score
            FROM docs
            ORDER BY scraped_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        print(f"[SEARCH] T3-RECENT found {len(rows)}")

        results = []
        for r in rows:
            learned = float(r.get("learned_score") or 1.0)
            combined = learned
            try:
                affinity = self.get_query_source_affinity(query, r.get("url"))
                if affinity > 0:
                    combined += 0.5
            except Exception:
                pass
            r["final_score"] = combined
            results.append(r)

        results.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
        return results


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
    
    def get_recent_docs(self, limit: int = 3) -> List[Dict]:
        """🔥 CRITICAL FALLBACK: Get most recent docs when search fails.
        
        This is the key to fixing "returns nothing" — when FTS search yields empty,
        we fallback to recent docs (they're probably relevant anyway).
        
        Args:
            limit: Number of docs to return
        
        Returns:
            List of recent docs with URL, title, snippet
        """
        cursor = self.conn.cursor()
        cursor.execute(
            """
            SELECT id, url, title, 
                   substr(content, 1, 400) AS snippet,
                   scraped_at
            FROM docs
            ORDER BY scraped_at DESC, id DESC
            LIMIT ?
            """,
            (limit,)
        )
        results = [dict(row) for row in cursor.fetchall()]
        
        # Format to match search_and_get output
        payload = []
        for row in results:
            payload.append({
                "url": row.get("url", ""),
                "title": row.get("title", "") or row.get("url", ""),
                "snippet": (row.get("snippet", "") or "")[:400],
                "score": 0.0  # No score, it's a fallback
            })
        
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
        like_query = f"%{query}%"

        results = []
        if language:
            cursor.execute(
                """
                SELECT
                    d.url,
                    d.title,
                    c.id,
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
                    c.id,
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
        results = [dict(row) for row in cursor.fetchall()]

        if len(results) < limit:
            remaining = limit - len(results)
            exclude_ids = [r["id"] for r in results]
            placeholders = ",".join("?" for _ in exclude_ids)
            
            if language:
                if exclude_ids:
                    sql = f"""
                        SELECT d.url, d.title, c.id, c.snippet, c.language, c.context, substr(c.snippet, 1, 100) AS highlighted, 0.0 AS score
                        FROM code_blocks c
                        JOIN docs d ON c.doc_id = d.id
                        WHERE (c.snippet LIKE ? OR c.context LIKE ?)
                          AND c.language = ?
                          AND c.id NOT IN ({placeholders})
                        LIMIT ?
                    """
                    cursor.execute(sql, (like_query, like_query, language, *exclude_ids, remaining))
                else:
                    sql = """
                        SELECT d.url, d.title, c.id, c.snippet, c.language, c.context, substr(c.snippet, 1, 100) AS highlighted, 0.0 AS score
                        FROM code_blocks c
                        JOIN docs d ON c.doc_id = d.id
                        WHERE (c.snippet LIKE ? OR c.context LIKE ?)
                          AND c.language = ?
                        LIMIT ?
                    """
                    cursor.execute(sql, (like_query, like_query, language, remaining))
            else:
                if exclude_ids:
                    sql = f"""
                        SELECT d.url, d.title, c.id, c.snippet, c.language, c.context, substr(c.snippet, 1, 100) AS highlighted, 0.0 AS score
                        FROM code_blocks c
                        JOIN docs d ON c.doc_id = d.id
                        WHERE (c.snippet LIKE ? OR c.context LIKE ?)
                          AND c.id NOT IN ({placeholders})
                        LIMIT ?
                    """
                    cursor.execute(sql, (like_query, like_query, *exclude_ids, remaining))
                else:
                    sql = """
                        SELECT d.url, d.title, c.id, c.snippet, c.language, c.context, substr(c.snippet, 1, 100) AS highlighted, 0.0 AS score
                        FROM code_blocks c
                        JOIN docs d ON c.doc_id = d.id
                        WHERE (c.snippet LIKE ? OR c.context LIKE ?)
                        LIMIT ?
                    """
                    cursor.execute(sql, (like_query, like_query, remaining))

            results.extend([dict(row) for row in cursor.fetchall()])
        
        # Remove 'id' from result dicts before returning to avoid confusing clients
        for r in results:
            r.pop("id", None)
            
        return results
    
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

    # ─────────────────────────────────────────────────────────────────────────
    # SCRAPE JOB TRACKING (NEW)
    # ─────────────────────────────────────────────────────────────────────────

    def get_scrape_job(self, query: str) -> Optional[Dict]:
        """Get scrape job status for a query."""
        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT query, status, updated_at, created_at FROM scrape_jobs WHERE query = ?",
            (query,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_scrape_job(self, query: str, status: str) -> None:
        """Create or update a scrape job (RUNNING, COMPLETED, or FAILED)."""
        from datetime import datetime
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()
        
        cursor.execute(
            """
            INSERT INTO scrape_jobs (query, status, updated_at, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(query) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (query, status, now, now)
        )
        self.conn.commit()

    def clear_stale_scrape_jobs(self, older_than_hours: int = 24) -> int:
        """Clear scrape jobs older than N hours."""
        from datetime import datetime, timedelta
        cursor = self.conn.cursor()
        cutoff = (datetime.utcnow() - timedelta(hours=older_than_hours)).isoformat()
        
        cursor.execute(
            "DELETE FROM scrape_jobs WHERE updated_at < ?",
            (cutoff,)
        )
        self.conn.commit()
        return cursor.rowcount
    
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
        """Prepare an FTS5 query with both AND and OR operators for better matching."""
        # Extract alphanumeric tokens, preserving case sensitivity
        tokens = [token for token in re.findall(r"[A-Za-z0-9_./:-]+", query) if len(token) > 0]
        if not tokens:
            return '""'
        # Use OR logic to cast a wider net in FTS5 searches
        # This makes "scrapee" match documents containing "scrapee" in any indexed field
        return " OR ".join(f'"{token}"*' for token in tokens)

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
    
    # ------------------------------------------------------------------ #
    # Spec-compliance aliases (MCP §4)                                      #
    # ------------------------------------------------------------------ #

    def search_with_snippets(self, query: str, limit: int = 10) -> List[Dict]:
        """Alias for search_docs() — returns results with FTS5 snippets.

        Required by MCP spec §4 search_with_snippets().
        """
        return self.search_docs(query, limit=limit)

    def search_code_with_context(self, query: str, language: str = None, limit: int = 10) -> List[Dict]:
        """Alias for search_code() — returns code blocks with surrounding context.

        Required by MCP spec §4 search_code_with_context().
        """
        return self.search_code(query, language=language, limit=limit)

    def search_with_filters(self, query: str, domain: str = None, language: str = None, 
                           content_type: str = None, date_after: str = None, limit: int = 10) -> List[Dict]:
        """Search with advanced filters."""
        cursor = self.conn.cursor()
        sql = "SELECT url, title, content FROM docs_fts WHERE docs_fts MATCH ?"
        params = [query]
        
        if domain:
            sql += " AND url LIKE ?"
            params.append(f"%{domain}%")
        
        if content_type == "code":
            sql = "SELECT url, title, snippet as content FROM code_fts WHERE code_fts MATCH ?"
            params = [query]
        
        if date_after:
            sql += " AND scraped_at >= ?"
            params.append(date_after)
        
        sql += " LIMIT ?"
        params.append(limit)
        
        rows = cursor.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def delete_document(self, url: str) -> bool:
        """Delete a document by URL."""
        cursor = self.conn.cursor()
        doc = cursor.execute("SELECT id FROM docs WHERE url = ?", (url,)).fetchone()
        if not doc:
            return False
        
        doc_id = doc["id"]
        cursor.execute("DELETE FROM code_blocks WHERE doc_id = ?", (doc_id,))
        cursor.execute("DELETE FROM doc_topics WHERE doc_id = ?", (doc_id,))
        cursor.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
        self.conn.commit()
        return True

    def delete_old_documents(self, older_than_days: int) -> int:
        """Delete documents older than N days."""
        from datetime import datetime, timedelta
        cutoff_date = (datetime.utcnow() - timedelta(days=older_than_days)).isoformat()
        
        cursor = self.conn.cursor()
        doc_ids = cursor.execute("SELECT id FROM docs WHERE scraped_at < ?", (cutoff_date,)).fetchall()
        
        deleted_count = 0
        for row in doc_ids:
            doc_id = row["id"]
            cursor.execute("DELETE FROM code_blocks WHERE doc_id = ?", (doc_id,))
            cursor.execute("DELETE FROM doc_topics WHERE doc_id = ?", (doc_id,))
            cursor.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
            deleted_count += 1
        
        self.conn.commit()
        return deleted_count

    def delete_domain_documents(self, domain: str) -> int:
        """Delete all documents from a domain."""
        cursor = self.conn.cursor()
        doc_ids = cursor.execute("SELECT id FROM docs WHERE domain = ? OR url LIKE ?", 
                                (domain, f"%{domain}%")).fetchall()
        
        deleted_count = 0
        for row in doc_ids:
            doc_id = row["id"]
            cursor.execute("DELETE FROM code_blocks WHERE doc_id = ?", (doc_id,))
            cursor.execute("DELETE FROM doc_topics WHERE doc_id = ?", (doc_id,))
            cursor.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
            deleted_count += 1
        
        self.conn.commit()
        return deleted_count

    def get_detailed_stats(self) -> Dict:
        """Get detailed index statistics."""
        cursor = self.conn.cursor()
        
        total_docs = cursor.execute("SELECT COUNT(*) as count FROM docs").fetchone()["count"]
        total_code = cursor.execute("SELECT COUNT(*) as count FROM code_blocks").fetchone()["count"]
        
        by_language = cursor.execute(
            "SELECT language, COUNT(*) as count FROM code_blocks WHERE language IS NOT NULL GROUP BY language"
        ).fetchall()
        
        by_domain = cursor.execute(
            "SELECT domain, COUNT(*) as count FROM docs WHERE domain IS NOT NULL GROUP BY domain"
        ).fetchall()
        
        last_update = cursor.execute(
            "SELECT MAX(scraped_at) as last FROM docs"
        ).fetchone()["last"]
        
        avg_size = cursor.execute(
            "SELECT AVG(LENGTH(content)) as avg FROM docs"
        ).fetchone()["avg"] or 0
        
        import os
        try:
            index_size = os.path.getsize(self.db_path) / 1024 / 1024
        except:
            index_size = 0
        
        return {
            "total_documents": total_docs,
            "total_code_blocks": total_code,
            "by_language": {row["language"]: row["count"] for row in by_language},
            "by_domain": {row["domain"]: row["count"] for row in by_domain},
            "avg_doc_size_bytes": int(avg_size),
            "index_size_mb": round(index_size, 2),
            "last_updated": last_update
        }

    def get_all_document_urls(self, limit: int = 100) -> List[str]:
        """Get all stored document URLs."""
        cursor = self.conn.cursor()
        rows = cursor.execute("SELECT url FROM docs LIMIT ?", (limit,)).fetchall()
        return [row["url"] for row in rows]

    def export_as_json(self) -> Dict:
        """Export index as JSON."""
        cursor = self.conn.cursor()
        
        docs = cursor.execute("SELECT url, title, content FROM docs LIMIT 50").fetchall()
        code_blocks = cursor.execute("SELECT snippet, language FROM code_blocks LIMIT 50").fetchall()
        
        return {
            "doc_count": len(docs),
            "code_block_count": len(code_blocks),
            "docs": [dict(row) for row in docs],
            "code_blocks": [dict(row) for row in code_blocks]
        }

    def record_source_feedback(self, query: str, urls: List[str], success: bool) -> None:
        """🧠 SELF-LEARNING #1: Record feedback for sources used in a response.
        
        Updates both source scores and query-source mapping to learn what works.
        
        Args:
            query: User's original query
            urls: List of source URLs that were returned
            success: True if user accepted/used answer, False if they rejected/re-asked
        """
        delta = 0.2 if success else -0.2
        
        cursor = self.conn.cursor()
        
        for url in urls:
            # Update source score (learned preference)
            cursor.execute("""
                UPDATE docs 
                SET score = MAX(0.1, MIN(5.0, score + ?))
                WHERE url = ?
            """, (delta, url))
            
            # Record query-source mapping (for personalization)
            action = "INSERT OR IGNORE" if success else "INSERT"
            if success:
                cursor.execute("""
                    INSERT INTO query_source_map (query, url, success_count) 
                    VALUES (?, ?, 1)
                    ON CONFLICT(query, url) DO UPDATE SET success_count = success_count + 1
                """, (query, url))
            else:
                cursor.execute("""
                    INSERT INTO query_source_map (query, url, failure_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(query, url) DO UPDATE SET failure_count = failure_count + 1
                """, (query, url))
        
        self.conn.commit()
        print(f"[LEARNING] Updated scores for {len(urls)} sources (success={success})")

    def get_source_score(self, url: str) -> float:
        """🧠 SELF-LEARNING #2: Get learned score for a source.
        
        Returns the adaptive score for a URL based on historical performance.
        Defaults to 1.0 if URL not found.
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT score FROM docs WHERE url = ?", (url,))
        row = cursor.fetchone()
        return row["score"] if row else 1.0

    def get_query_source_affinity(self, query: str, url: str) -> int:
        """🧠 SELF-LEARNING #3: Check if this source has helped with this query before.
        
        Returns success_count - failure_count (positive = good source for this query).
        Used for personalizing results based on history.
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT success_count - failure_count as affinity 
            FROM query_source_map 
            WHERE query = ? AND url = ?
        """, (query, url))
        row = cursor.fetchone()
        return row["affinity"] if row else 0

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
