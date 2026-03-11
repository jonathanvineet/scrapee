"""
Redis Storage Layer for MCP Server
Handles persistence of scraped documentation with fallback to in-memory storage.
"""
import os
import json
import redis
from typing import Optional, Dict, List


class RedisStore:
    """Redis storage layer with in-memory fallback for scraped documentation."""
    
    def __init__(self):
        self.redis_client = None
        self.memory_store = {}  # Fallback storage
        self._init_redis()
    
    def _init_redis(self):
        """Initialize Redis connection with multiple fallback strategies."""
        try:
            redis_url = os.getenv('REDIS_URL')
            if redis_url:
                self.redis_client = redis.from_url(
                    redis_url, 
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
            else:
                # Fallback to individual connection params
                redis_host = os.getenv('REDIS_HOST', 'localhost')
                redis_port = int(os.getenv('REDIS_PORT', 6379))
                redis_password = os.getenv('REDIS_PASSWORD')
                
                self.redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    password=redis_password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )
            
            # Test connection
            self.redis_client.ping()
            print("✓ Redis connected successfully")
            
        except Exception as e:
            print(f"⚠ Redis connection failed: {e}. Using in-memory storage.")
            self.redis_client = None
    
    def save_doc(self, url: str, content: str, metadata: Optional[Dict] = None) -> bool:
        """
        Save document content to storage.
        
        Args:
            url: Document URL (used as key)
            content: Document text content
            metadata: Optional metadata (title, timestamp, etc.)
        
        Returns:
            True if saved successfully
        """
        key = f"doc:{url}"
        
        doc_data = {
            "url": url,
            "content": content,
            "metadata": metadata or {}
        }
        
        try:
            if self.redis_client:
                # Save as JSON string
                self.redis_client.set(key, json.dumps(doc_data))
                # Also add to sorted set for listing
                self.redis_client.sadd("doc:index", url)
            else:
                self.memory_store[key] = doc_data
            
            return True
            
        except Exception as e:
            print(f"Error saving doc {url}: {e}")
            # Fallback to memory
            self.memory_store[key] = doc_data
            return True
    
    def get_doc(self, url: str) -> Optional[Dict]:
        """
        Retrieve document by URL.
        
        Args:
            url: Document URL
        
        Returns:
            Document data dict or None if not found
        """
        key = f"doc:{url}"
        
        try:
            if self.redis_client:
                data = self.redis_client.get(key)
                if data:
                    return json.loads(data)
            else:
                return self.memory_store.get(key)
                
        except Exception as e:
            print(f"Error retrieving doc {url}: {e}")
            return self.memory_store.get(key)
        
        return None
    
    def list_docs(self) -> List[str]:
        """
        List all stored document URLs.
        
        Returns:
            List of document URLs
        """
        try:
            if self.redis_client:
                # Get from index set
                urls = self.redis_client.smembers("doc:index")
                return sorted(list(urls))
            else:
                # Parse from memory store keys
                urls = [k.replace("doc:", "") for k in self.memory_store.keys() if k.startswith("doc:")]
                return sorted(urls)
                
        except Exception as e:
            print(f"Error listing docs: {e}")
            urls = [k.replace("doc:", "") for k in self.memory_store.keys() if k.startswith("doc:")]
            return sorted(urls)
    
    def delete_doc(self, url: str) -> bool:
        """
        Delete document by URL.
        
        Args:
            url: Document URL
        
        Returns:
            True if deleted successfully
        """
        key = f"doc:{url}"
        
        try:
            if self.redis_client:
                self.redis_client.delete(key)
                self.redis_client.srem("doc:index", url)
            else:
                if key in self.memory_store:
                    del self.memory_store[key]
            
            return True
            
        except Exception as e:
            print(f"Error deleting doc {url}: {e}")
            return False
    
    def get_all_docs(self) -> Dict[str, str]:
        """
        Retrieve all documents as a dictionary mapping URLs to content.
        
        Returns:
            Dict of {url: content}
        """
        docs = {}
        urls = self.list_docs()
        
        for url in urls:
            doc = self.get_doc(url)
            if doc:
                docs[url] = doc.get("content", "")
        
        return docs
    
    def clear_all(self) -> bool:
        """
        Clear all stored documents. Use with caution!
        
        Returns:
            True if successful
        """
        try:
            if self.redis_client:
                # Delete all doc:* keys
                for url in self.list_docs():
                    self.redis_client.delete(f"doc:{url}")
                self.redis_client.delete("doc:index")
            else:
                self.memory_store.clear()
            
            return True
            
        except Exception as e:
            print(f"Error clearing docs: {e}")
            return False


# Global singleton instance
_store = None

def get_store() -> RedisStore:
    """Get or create the global RedisStore instance."""
    global _store
    if _store is None:
        _store = RedisStore()
    return _store
