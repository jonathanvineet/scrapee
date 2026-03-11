"""
Vector Search Engine for MCP Server
Provides semantic search using sentence embeddings for documentation retrieval.
"""
import os
import numpy as np
from typing import List, Dict, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Try to use sentence-transformers if available, fallback to TF-IDF
_USE_EMBEDDINGS = False
_model = None

try:
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer("all-MiniLM-L6-v2")
    _USE_EMBEDDINGS = True
    print("✓ Using sentence-transformers for semantic search")
except ImportError:
    print("⚠ sentence-transformers not available. Using TF-IDF fallback.")
    _USE_EMBEDDINGS = False


class VectorSearch:
    """
    Vector search engine with dual implementation:
    1. Sentence embeddings (preferred) - better semantic understanding
    2. TF-IDF (fallback) - lightweight, no external dependencies
    """
    
    def __init__(self, use_embeddings: bool = True):
        """
        Initialize vector search engine.
        
        Args:
            use_embeddings: Try to use sentence embeddings if available
        """
        self.use_embeddings = use_embeddings and _USE_EMBEDDINGS
        self.vectorizer = None
        self.tfidf_matrix = None
        self.doc_urls = []
        
        if self.use_embeddings:
            self.model = _model
        else:
            self.vectorizer = TfidfVectorizer(
                max_features=1000,
                stop_words='english',
                ngram_range=(1, 2)
            )
    
    def embed(self, text: str) -> np.ndarray:
        """
        Generate embedding for text.
        
        Args:
            text: Input text
        
        Returns:
            Embedding vector as numpy array
        """
        if self.use_embeddings:
            return self.model.encode(text)
        else:
            # TF-IDF fallback requires fitting first
            raise NotImplementedError("Use search() method for TF-IDF")
    
    @staticmethod
    def cosine_similarity_score(a: np.ndarray, b: np.ndarray) -> float:
        """
        Calculate cosine similarity between two vectors.
        
        Args:
            a: First vector
            b: Second vector
        
        Returns:
            Similarity score (0-1)
        """
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    def search_with_embeddings(
        self, 
        query: str, 
        docs: Dict[str, str], 
        k: int = 3
    ) -> List[Tuple[str, float]]:
        """
        Search using sentence embeddings.
        
        Args:
            query: Search query
            docs: Dictionary mapping URLs to text content
            k: Number of results to return
        
        Returns:
            List of (url, score) tuples sorted by relevance
        """
        if not docs:
            return []
        
        query_embedding = self.embed(query)
        
        scored = []
        for url, text in docs.items():
            # Use first 1000 characters for efficiency
            snippet = text[:1000]
            doc_embedding = self.embed(snippet)
            score = self.cosine_similarity_score(query_embedding, doc_embedding)
            scored.append((url, float(score)))
        
        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)
        
        return scored[:k]
    
    def search_with_tfidf(
        self, 
        query: str, 
        docs: Dict[str, str], 
        k: int = 3
    ) -> List[Tuple[str, float]]:
        """
        Search using TF-IDF vectorization.
        
        Args:
            query: Search query
            docs: Dictionary mapping URLs to text content
            k: Number of results to return
        
        Returns:
            List of (url, score) tuples sorted by relevance
        """
        if not docs:
            return []
        
        # Prepare documents
        self.doc_urls = list(docs.keys())
        doc_texts = [docs[url][:2000] for url in self.doc_urls]  # Limit length
        
        # Fit TF-IDF
        try:
            self.tfidf_matrix = self.vectorizer.fit_transform(doc_texts)
            query_vector = self.vectorizer.transform([query])
            
            # Calculate similarity
            similarities = cosine_similarity(query_vector, self.tfidf_matrix).flatten()
            
            # Get top k results
            top_indices = np.argsort(similarities)[::-1][:k]
            
            results = [
                (self.doc_urls[idx], float(similarities[idx])) 
                for idx in top_indices
            ]
            
            return results
            
        except Exception as e:
            print(f"TF-IDF search error: {e}")
            # Return first k docs as fallback
            return [(url, 0.5) for url in list(docs.keys())[:k]]
    
    def search(
        self, 
        query: str, 
        docs: Dict[str, str], 
        k: int = 3
    ) -> List[Tuple[str, float]]:
        """
        Search documents using the best available method.
        
        Args:
            query: Search query
            docs: Dictionary mapping URLs to text content
            k: Number of results to return
        
        Returns:
            List of (url, score) tuples sorted by relevance
        """
        if self.use_embeddings:
            return self.search_with_embeddings(query, docs, k)
        else:
            return self.search_with_tfidf(query, docs, k)
    
    def search_and_get(
        self, 
        query: str, 
        docs: Dict[str, str], 
        k: int = 3,
        snippet_length: int = 1500
    ) -> List[Dict]:
        """
        Search and return formatted results with snippets.
        
        Args:
            query: Search query
            docs: Dictionary mapping URLs to text content
            k: Number of results to return
            snippet_length: Length of text snippet to include
        
        Returns:
            List of result dictionaries with url, score, and snippet
        """
        results = self.search(query, docs, k)
        
        formatted_results = []
        for url, score in results:
            text = docs.get(url, "")
            snippet = text[:snippet_length]
            
            formatted_results.append({
                "url": url,
                "score": round(score, 3),
                "snippet": snippet,
                "length": len(text)
            })
        
        return formatted_results


# Global singleton instance
_search_engine = None

def get_search_engine() -> VectorSearch:
    """Get or create the global VectorSearch instance."""
    global _search_engine
    if _search_engine is None:
        _search_engine = VectorSearch()
    return _search_engine
