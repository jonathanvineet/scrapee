"""
SQLite Storage Layer for Production MCP Server
Provides structured indexing for documents, code blocks, and metadata.
"""
import sqlite3
import json
import os
from typing import Optional, Dict, List, Tuple
from datetime import datetime
import hashlib


class SQLiteStore:
    """
    SQLite-backed storage for production MCP server.
    
    Features:
    - Structured document storage with metadata
    - Code block extraction and indexing
    - Full-text search support
    - Efficient retrieval and caching
    """
    
    def __init__(self, db_path: str = None):
        """
        Initialize SQLite storage.
        
        Args:
            db_path: Path to SQLite database file (default: backend/db/docs.db)
        """
        if db_path is None:
            # Default path relative to backend directory
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_dir = os.path.join(backend_dir, "db")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "docs.db")
        
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        self._init_schema()
        print(f"✓ SQLite initialized: {db_path}")
    
    def _init_schema(self):
        """Create database schema with indexes."""
        cursor = self.conn.cursor()
        
        # Documents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS docs (
                url TEXT PRIMARY KEY,
                title TEXT,
                content TEXT,
                domain TEXT,
                language TEXT,
                scraped_at TEXT,
                metadata TEXT
            )
        """)
        
        # Code blocks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS code_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                snippet TEXT,
                language TEXT,
                context TEXT,
                line_number INTEGER,
                FOREIGN KEY (url) REFERENCES docs(url) ON DELETE CASCADE
            )
        """)
        
        # Topics/headings table for structured navigation
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS doc_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                topic TEXT,
                heading TEXT,
                level INTEGER,
                content TEXT,
                FOREIGN KEY (url) REFERENCES docs(url) ON DELETE CASCADE
            )
        """)
        
        # Create full-text search virtual tables (FTS5)
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts 
            USING fts5(url, title, content)
        """)
        
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS code_fts 
            USING fts5(snippet, language, context)
        """)
        
        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_domain ON docs(domain)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_url ON code_blocks(url)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_code_language ON code_blocks(language)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_topics_url ON doc_topics(url)")
        
        self.conn.commit()
    
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
            
            # Save document
            cursor.execute("""
                INSERT OR REPLACE INTO docs 
                (url, title, content, domain, language, scraped_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (url, title, content, domain, language, scraped_at, json.dumps(metadata)))
            
            # Save to FTS
            cursor.execute("""
                INSERT OR REPLACE INTO docs_fts (url, title, content)
                VALUES (?, ?, ?)
            """, (url, title, content))
            
            # Save code blocks
            if code_blocks:
                # Delete existing code blocks for this URL
                cursor.execute("DELETE FROM code_blocks WHERE url = ?", (url,))
                
                for block in code_blocks:
                    cursor.execute("""
                        INSERT INTO code_blocks 
                        (url, snippet, language, context, line_number)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        url,
                        block.get("snippet", ""),
                        block.get("language", ""),
                        block.get("context", ""),
                        block.get("line_number", 0)
                    ))
                    
                    # Save to FTS
                    cursor.execute("""
                        INSERT INTO code_fts (snippet, language, context)
                        VALUES (?, ?, ?)
                    """, (
                        block.get("snippet", ""),
                        block.get("language", ""),
                        block.get("context", "")
                    ))
            
            # Save topics/headings
            if topics:
                # Delete existing topics for this URL
                cursor.execute("DELETE FROM doc_topics WHERE url = ?", (url,))
                
                for topic in topics:
                    cursor.execute("""
                        INSERT INTO doc_topics 
                        (url, topic, heading, level, content)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        url,
                        topic.get("topic", ""),
                        topic.get("heading", ""),
                        topic.get("level", 0),
                        topic.get("content", "")
                    ))
            
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
            SELECT url, title, content, domain, language, scraped_at, metadata
            FROM docs WHERE url = ?
        """, (url,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return {
            "url": row["url"],
            "title": row["title"],
            "content": row["content"],
            "domain": row["domain"],
            "language": row["language"],
            "scraped_at": row["scraped_at"],
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
        }
    
    def list_docs(self) -> List[str]:
        """
        List all document URLs.
        
        Returns:
            List of URLs
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT url FROM docs ORDER BY scraped_at DESC")
        return [row["url"] for row in cursor.fetchall()]
    
    def get_all_docs(self) -> Dict[str, str]:
        """
        Get all documents as URL -> content mapping.
        
        Returns:
            Dict mapping URL to content
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT url, content FROM docs")
        return {row["url"]: row["content"] for row in cursor.fetchall()}
    
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
        cursor.execute("""
            SELECT 
                d.url,
                d.title,
                snippet(docs_fts, 2, '<mark>', '</mark>', '...', 64) as snippet,
                rank
            FROM docs_fts
            JOIN docs d ON docs_fts.url = d.url
            WHERE docs_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        
        return [dict(row) for row in cursor.fetchall()]
    
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
        
        if language:
            cursor.execute("""
                SELECT 
                    c.snippet,
                    c.language,
                    c.context,
                    c.url,
                    d.title,
                    snippet(code_fts, 0, '<mark>', '</mark>', '...', 32) as highlighted
                FROM code_fts
                JOIN code_blocks c ON code_fts.rowid = c.id
                JOIN docs d ON c.url = d.url
                WHERE code_fts MATCH ? AND c.language = ?
                ORDER BY rank
                LIMIT ?
            """, (query, language, limit))
        else:
            cursor.execute("""
                SELECT 
                    c.snippet,
                    c.language,
                    c.context,
                    c.url,
                    d.title,
                    snippet(code_fts, 0, '<mark>', '</mark>', '...', 32) as highlighted
                FROM code_fts
                JOIN code_blocks c ON code_fts.rowid = c.id
                JOIN docs d ON c.url = d.url
                WHERE code_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit))
        
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
        cursor.execute("""
            SELECT url, title, scraped_at
            FROM docs
            WHERE domain = ?
            ORDER BY scraped_at DESC
        """, (domain,))
        
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
        cursor.execute("""
            SELECT topic, heading, level, content
            FROM doc_topics
            WHERE url = ?
            ORDER BY id
        """, (url,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def search_with_snippets(self, query: str, limit: int = 5) -> List[Dict]:
        """
        FTS5 search with highlighted snippets — use this instead of TF-IDF.
        
        Args:
            query: Search query
            limit: Maximum results to return
        
        Returns:
            List of dicts with url, title, snippet, rank
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT 
                    d.url,
                    d.title,
                    snippet(docs_fts, 1, '[', ']', '...', 30) as snippet,
                    rank
                FROM docs d
                JOIN docs_fts ON d.url = docs_fts.url
                WHERE docs_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"[SQLiteStore] search_with_snippets error: {e}")
            return []
    
    def search_code_with_context(self, query: str, language: str = None, limit: int = 5) -> List[Dict]:
        """
        Search code blocks with optional language filter.
        
        Args:
            query: Search query
            language: Optional programming language filter
            limit: Maximum results
        
        Returns:
            List of dicts with snippet, language, context, url, title
        """
        try:
            cursor = self.conn.cursor()
            
            if language:
                cursor.execute("""
                    SELECT 
                        c.snippet,
                        c.language,
                        c.context,
                        c.url,
                        d.title,
                        snippet(code_fts, 0, '[', ']', '...', 20) as highlighted
                    FROM code_fts
                    JOIN code_blocks c ON code_fts.rowid = c.rowid
                    JOIN docs d ON c.url = d.url
                    WHERE code_fts MATCH ? AND c.language = ?
                    ORDER BY rank
                    LIMIT ?
                """, (query, language, limit))
            else:
                cursor.execute("""
                    SELECT 
                        c.snippet,
                        c.language,
                        c.context,
                        c.url,
                        d.title,
                        snippet(code_fts, 0, '[', ']', '...', 20) as highlighted
                    FROM code_fts
                    JOIN code_blocks c ON code_fts.rowid = c.rowid
                    JOIN docs d ON c.url = d.url
                    WHERE code_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (query, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            print(f"[SQLiteStore] search_code_with_context error: {e}")
            return []
    
    def get_stats(self) -> Dict:
        """
        Get storage statistics — used by health endpoint.
        
        Returns:
            Dict with counts and info
        """
        try:
            cursor = self.conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as count FROM docs")
            doc_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM code_blocks")
            code_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(DISTINCT domain) as count FROM docs")
            domain_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT domain, COUNT(*) as count FROM docs GROUP BY domain ORDER BY count DESC LIMIT 5")
            top_domains = [dict(row) for row in cursor.fetchall()]
            
            return {
                "total_docs": doc_count,
                "total_code_blocks": code_count,
                "total_domains": domain_count,
                "top_domains": top_domains
            }
        except Exception as e:
            return {"total_docs": 0, "total_code_blocks": 0, "error": str(e)}
    
    def get_doc_by_url(self, url: str) -> Optional[Dict]:
        """
        Fetch a single document by URL.
        
        Args:
            url: Document URL
        
        Returns:
            Dict with document data or None if not found
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT url, title, content, domain, language, scraped_at, metadata FROM docs WHERE url = ?",
                (url,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            return None
    
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
