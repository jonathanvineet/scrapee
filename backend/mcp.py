import ipaddress
import json
import os
import signal
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

from storage.sqlite_store import get_sqlite_store
from smart_scraper import create_scraper
from utils.normalize import normalize_url


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "scrapee"
SERVER_VERSION = "1.0.0"
SCRAPE_TIMEOUT_SECONDS = 8


IMPORT_ERRORS: Dict[str, str] = {}

try:
	from smart_crawler import SmartCrawler
	SMART_CRAWLER_AVAILABLE = True
except Exception as exc:
	SmartCrawler = None
	SMART_CRAWLER_AVAILABLE = False
	IMPORT_ERRORS["smart_crawler"] = str(exc)

try:
	from selenium_crawler import SeleniumCrawler
	SELENIUM_AVAILABLE = True
except Exception as exc:
	SeleniumCrawler = None
	SELENIUM_AVAILABLE = False
	IMPORT_ERRORS["selenium_crawler"] = str(exc)

try:
	from pipeline_crawler import UltraFastCrawler
	ULTRAFAST_AVAILABLE = True
except Exception as exc:
	UltraFastCrawler = None
	ULTRAFAST_AVAILABLE = False
	IMPORT_ERRORS["pipeline_crawler"] = str(exc)


class TimeoutException(Exception):
	"""Raised when a scrape exceeds the configured timeout."""


def timeout_handler(signum, frame):
	raise TimeoutException()


if hasattr(signal, "SIGALRM"):
	signal.signal(signal.SIGALRM, timeout_handler)


class CacheLayer:
	"""Simple in-process TTL cache for deterministic read operations."""

	def __init__(self, ttl_seconds: int = 300):
		self.ttl_seconds = ttl_seconds
		self._cache: Dict[str, Tuple[float, Any]] = {}

	def get(self, key: str) -> Optional[Any]:
		cached = self._cache.get(key)
		if not cached:
			return None
		expires_at, value = cached
		if expires_at < time.monotonic():
			self._cache.pop(key, None)
			return None
		return value

	def set(self, key: str, value: Any) -> None:
		self._cache[key] = (time.monotonic() + self.ttl_seconds, value)

	def clear(self) -> None:
		self._cache.clear()


class MCPServer:
	"""Single JSON-RPC MCP server for the backend."""

	blocked_hostnames = {"localhost", "0.0.0.0", "127.0.0.1", "::1"}
	blocked_suffixes = (".local", ".internal")

	def __init__(self):
		self.store = get_sqlite_store()
		self.scraper = create_scraper()
		self.cache = CacheLayer(ttl_seconds=300)
		self.name = SERVER_NAME
		self.version = SERVER_VERSION

	def handle_request(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
		if not isinstance(data, dict):
			return self._error_response(None, -32600, "Invalid Request")

		method = data.get("method")
		request_id = data.get("id")
		params = data.get("params") or {}

		if not method:
			return self._error_response(request_id, -32600, "Method is required")

		if request_id is None and method.startswith("notifications/"):
			return None

		handlers = {
			"initialize": self._handle_initialize,
			"tools/list": self._handle_tools_list,
			"tools/call": self._handle_tools_call,
			"resources/list": self._handle_resources_list,
			"resources/read": self._handle_resources_read,
			"prompts/list": self._handle_prompts_list,
			"prompts/get": self._handle_prompts_get,
		}

		handler = handlers.get(method)
		if handler is None:
			if request_id is None:
				return None
			return self._error_response(request_id, -32601, f"Method not found: {method}")

		try:
			return handler(request_id, params)
		except Exception as exc:
			return self._error_response(request_id, -32603, f"Internal error: {exc}")

	def _handle_initialize(self, request_id: Any, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
		return self._success_response(
			request_id,
			{
				"protocolVersion": PROTOCOL_VERSION,
				"capabilities": {
					"tools": {},
					"resources": {},
					"prompts": {},
				},
				"serverInfo": {
					"name": self.name,
					"version": self.version,
				},
			},
		)

	def _handle_tools_list(self, request_id: Any, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
		return self._success_response(
			request_id,
			{
				"tools": [
					{
						"name": "search_and_get",
						"description": "Use when you want the best documentation hits and short snippets in one round trip. Input: query string, optional limit integer, optional snippet_length integer. Output: object with query, total, and results[{url, title, snippet, score}].",
						"inputSchema": {
							"type": "object",
							"properties": {
								"query": {"type": "string"},
								"limit": {"type": "integer", "default": 5},
								"snippet_length": {"type": "integer", "default": 400},
							},
							"required": ["query"],
						},
					},
					{
						"name": "scrape_url",
						"description": "Use when a required document is missing and needs to be fetched and indexed. Input: url string, optional mode enum, optional max_depth integer. Output: object with requested URL, scrape mode, pages_scraped, stored_urls, and any skipped pages or errors.",
						"inputSchema": {
							"type": "object",
							"properties": {
								"url": {"type": "string"},
								"mode": {
									"type": "string",
									"enum": ["smart", "ultrafast", "selenium"],
									"default": "smart",
								},
								"max_depth": {"type": "integer", "default": 0},
							},
							"required": ["url"],
						},
					},
					{
						"name": "search_docs",
						"description": "Use when you only need matching document identifiers before a separate fetch. Input: query string and optional limit integer. Output: object with query, total, and urls[].",
						"inputSchema": {
							"type": "object",
							"properties": {
								"query": {"type": "string"},
								"limit": {"type": "integer", "default": 10},
							},
							"required": ["query"],
						},
					},
					{
						"name": "search_code",
						"description": "Use when you need indexed code examples from scraped docs. Input: query string, optional language string, optional limit integer. Output: object with query, total, and results[{url, title, language, context, snippet, highlighted, score}].",
						"inputSchema": {
							"type": "object",
							"properties": {
								"query": {"type": "string"},
								"language": {"type": "string"},
								"limit": {"type": "integer", "default": 5},
							},
							"required": ["query"],
						},
					},
					{
						"name": "list_docs",
						"description": "Use when you need an overview of indexed documentation. Input: optional limit integer. Output: object with total count, urls[], and storage stats.",
						"inputSchema": {
							"type": "object",
							"properties": {
								"limit": {"type": "integer", "default": 50},
							},
						},
					},
					{
						"name": "get_doc",
						"description": "Use when you already know the exact document URL and need the stored content. Input: url string. Output: object with url, title, content, metadata, topics, and code_blocks.",
						"inputSchema": {
							"type": "object",
							"properties": {
								"url": {"type": "string"},
							},
							"required": ["url"],
						},
					},
				]
			},
		)

	def _handle_tools_call(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
		tool_name = params.get("name")
		arguments = params.get("arguments") or {}
		if isinstance(arguments, str):
			try:
				arguments = json.loads(arguments)
			except json.JSONDecodeError:
				arguments = {}

		tools = {
			"search_and_get": self._tool_search_and_get,
			"scrape_url": self._tool_scrape_url,
			"search_docs": self._tool_search_docs,
			"search_code": self._tool_search_code,
			"list_docs": self._tool_list_docs,
			"get_doc": self._tool_get_doc,
		}

		handler = tools.get(tool_name)
		if handler is None:
			return self._error_response(request_id, -32602, f"Unknown tool: {tool_name}")

		result = handler(arguments)
		return self._success_response(
			request_id,
			{
				"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
				"structuredContent": result,
			},
		)

	def _handle_resources_list(self, request_id: Any, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
		stats = self.store.get_stats()
		docs = self.store.get_doc_summaries(limit=25)
		resources = [
			{
				"uri": "docs://stats",
				"name": "Storage stats",
				"description": "SQLite-backed index statistics and crawler availability.",
				"mimeType": "application/json",
			},
			{
				"uri": "docs://domains",
				"name": "Indexed domains",
				"description": "List of indexed domains and document counts.",
				"mimeType": "application/json",
			},
		]

		for doc in docs:
			url = doc.get("url", "")
			resources.append(
				{
					"uri": self._doc_resource_uri(url),
					"name": doc.get("title") or url,
					"description": f"Stored document for {url}",
					"mimeType": "text/plain",
				}
			)

		return self._success_response(request_id, {"resources": resources, "stats": stats})

	def _handle_resources_read(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
		uri = params.get("uri", "")
		if uri == "docs://stats":
			content = {
				"stats": self.store.get_stats(),
				"crawlers": self._crawler_status(),
				"import_errors": IMPORT_ERRORS,
			}
			return self._success_response(
				request_id,
				{
					"contents": [
						{
							"uri": uri,
							"mimeType": "application/json",
							"text": json.dumps(content, ensure_ascii=False, indent=2),
						}
					]
				},
			)

		if uri == "docs://domains":
			content = self.store.list_domains()
			return self._success_response(
				request_id,
				{
					"contents": [
						{
							"uri": uri,
							"mimeType": "application/json",
							"text": json.dumps(content, ensure_ascii=False, indent=2),
						}
					]
				},
			)

		if uri.startswith("docs://document/"):
			encoded = uri.split("docs://document/", 1)[1]
			doc = self.store.get_doc(unquote(encoded))
			if not doc:
				return self._error_response(request_id, -32602, f"Unknown resource: {uri}")
			return self._success_response(
				request_id,
				{
					"contents": [
						{
							"uri": uri,
							"mimeType": "text/plain",
							"text": doc.get("content", ""),
						}
					]
				},
			)

		return self._error_response(request_id, -32602, f"Unknown resource: {uri}")

	def _handle_prompts_list(self, request_id: Any, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
		return self._success_response(
			request_id,
			{
				"prompts": [
					{
						"name": "answer_with_docs",
						"description": "Build a grounded answer from the most relevant documentation snippets.",
						"arguments": [
							{"name": "question", "description": "Question to answer with docs", "required": True}
						],
					},
					{
						"name": "implement_with_code",
						"description": "Gather docs and code examples for an implementation task.",
						"arguments": [
							{"name": "task", "description": "Implementation task", "required": True}
						],
					},
				]
			},
		)

	def _handle_prompts_get(self, request_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
		name = params.get("name", "")
		arguments = params.get("arguments") or {}

		if name == "answer_with_docs":
			question = str(arguments.get("question", "")).strip()
			docs = self.store.search_and_get(question, limit=3, snippet_length=500)
			text = self._render_prompt(
				header=f"Answer the question using the documentation context only: {question}",
				docs=docs,
				code=[],
			)
			return self._prompt_response(request_id, text)

		if name == "implement_with_code":
			task = str(arguments.get("task", "")).strip()
			docs = self.store.search_and_get(task, limit=3, snippet_length=400)
			code = self.store.search_code(task, limit=3)
			text = self._render_prompt(
				header=f"Plan and implement this task using the provided documentation and code examples: {task}",
				docs=docs,
				code=code,
			)
			return self._prompt_response(request_id, text)

		return self._error_response(request_id, -32602, f"Unknown prompt: {name}")

	def _tool_search_and_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
		query = str(args.get("query", "")).strip()
		limit = self._coerce_int(args.get("limit", args.get("k", 5)), default=5, minimum=1, maximum=10)
		snippet_length = self._coerce_int(args.get("snippet_length", 400), default=400, minimum=100, maximum=2000)
		if not query:
			return {"error": "query is required"}

		cache_key = f"search_and_get:{query}:{limit}:{snippet_length}"
		cached = self.cache.get(cache_key)
		if cached is not None:
			return cached

		results = self.store.search_and_get(query, limit=limit, snippet_length=snippet_length)
		payload = {"query": query, "total": len(results), "results": results}
		self.cache.set(cache_key, payload)
		return payload

	def _tool_search_docs(self, args: Dict[str, Any]) -> Dict[str, Any]:
		query = str(args.get("query", "")).strip()
		limit = self._coerce_int(args.get("limit", 10), default=10, minimum=1, maximum=25)
		if not query:
			return {"error": "query is required"}

		cache_key = f"search_docs:{query}:{limit}"
		cached = self.cache.get(cache_key)
		if cached is not None:
			return cached

		results = self.store.search_docs(query, limit=limit)
		payload = {
			"query": query,
			"total": len(results),
			"urls": [item["url"] for item in results],
		}
		self.cache.set(cache_key, payload)
		return payload

	def _tool_search_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
		query = str(args.get("query", "")).strip()
		language = str(args.get("language", "")).strip() or None
		limit = self._coerce_int(args.get("limit", 5), default=5, minimum=1, maximum=20)
		if not query:
			return {"error": "query is required"}

		cache_key = f"search_code:{query}:{language}:{limit}"
		cached = self.cache.get(cache_key)
		if cached is not None:
			return cached

		results = self.store.search_code(query, language=language, limit=limit)
		payload = {"query": query, "language": language, "total": len(results), "results": results}
		self.cache.set(cache_key, payload)
		return payload

	def _tool_list_docs(self, args: Dict[str, Any]) -> Dict[str, Any]:
		limit = self._coerce_int(args.get("limit", 50), default=50, minimum=1, maximum=200)
		docs = self.store.list_docs(limit=limit)
		return {"total": self.store.get_stats().get("total_docs", 0), "urls": docs, "stats": self.store.get_stats()}

	def _tool_get_doc(self, args: Dict[str, Any]) -> Dict[str, Any]:
		url = normalize_url(str(args.get("url", "")).strip())
		if not url:
			return {"error": "url is required"}
		doc = self.store.get_doc(url)
		if not doc:
			return {"error": f"document not found: {url}"}
		return doc

	def _tool_scrape_url(self, args: Dict[str, Any]) -> Dict[str, Any]:
		raw_url = str(args.get("url", "")).strip()
		mode = str(args.get("mode", "smart")).strip().lower() or "smart"
		max_depth = self._coerce_int(args.get("max_depth", 0), default=0, minimum=0, maximum=2)

		if not raw_url:
			return {"error": "url is required"}

		is_valid, error_message = self._validate_scrape_url(raw_url)
		if not is_valid:
			return {"error": error_message, "url": raw_url}

		url = normalize_url(raw_url)
		crawler = self._build_crawler(mode, url, max_depth)
		if crawler is None:
			return {"error": f"crawler mode '{mode}' is unavailable", "url": url, "mode": mode}

		try:
			pages = self._run_with_timeout(crawler.crawl, timeout=SCRAPE_TIMEOUT_SECONDS)
		except TimeoutException:
			return {"error": "timeout", "url": url, "mode": mode}
		except Exception as exc:
			return {"error": f"scrape failed: {exc}", "url": url, "mode": mode}

		stored_urls: List[str] = []
		skipped: List[Dict[str, str]] = []

		for page_url, html in (pages or {}).items():
			normalized_page_url = normalize_url(page_url)
			page_valid, page_error = self._validate_scrape_url(normalized_page_url)
			if not page_valid:
				skipped.append({"url": normalized_page_url, "reason": page_error})
				continue

			try:
				parsed = self.scraper.parse_html(html, normalized_page_url)
				self.store.save_doc(
					normalized_page_url,
					parsed.get("content", ""),
					metadata=parsed.get("metadata", {}),
					code_blocks=parsed.get("code_blocks", []),
					topics=parsed.get("topics", []),
				)
				stored_urls.append(normalized_page_url)
			except Exception as exc:
				skipped.append({"url": normalized_page_url, "reason": str(exc)})

		self.cache.clear()
		return {
			"url": url,
			"mode": mode,
			"max_depth": max_depth,
			"pages_scraped": len(stored_urls),
			"stored_urls": stored_urls,
			"skipped": skipped,
		}

	def _build_crawler(self, mode: str, url: str, max_depth: int):
		if mode == "selenium" and SELENIUM_AVAILABLE:
			return SeleniumCrawler(start_url=url, max_depth=max_depth)
		if mode == "ultrafast" and ULTRAFAST_AVAILABLE:
			return UltraFastCrawler(start_url=url, max_depth=max_depth, max_workers=4)
		if mode == "smart" and SMART_CRAWLER_AVAILABLE:
			return SmartCrawler(start_url=url, max_depth=max_depth)
		return None

	def _validate_scrape_url(self, url: str) -> Tuple[bool, str]:
		parsed = urlparse(url)
		if parsed.scheme not in {"http", "https"}:
			return False, "invalid scheme: only http and https are allowed"
		hostname = (parsed.hostname or "").lower()
		if not hostname:
			return False, "url must include a hostname"
		if hostname in self.blocked_hostnames or hostname.endswith(self.blocked_suffixes):
			return False, "blocked internal URL"
		try:
			ip = ipaddress.ip_address(hostname)
			if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
				return False, "blocked internal URL"
		except ValueError:
			pass
		return True, ""

	def _run_with_timeout(self, callback: Callable[[], Any], timeout: int) -> Any:
		if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
			return callback()

		previous = signal.getsignal(signal.SIGALRM)
		signal.signal(signal.SIGALRM, timeout_handler)
		try:
			signal.alarm(timeout)
			return callback()
		finally:
			signal.alarm(0)
			signal.signal(signal.SIGALRM, previous)

	def _render_prompt(self, header: str, docs: List[Dict[str, Any]], code: List[Dict[str, Any]]) -> str:
		sections = [header, "", "Documentation:"]
		if docs:
			for item in docs:
				sections.append(f"- {item.get('title') or item.get('url')}: {item.get('snippet', '')}")
		else:
			sections.append("- No documentation matches found.")

		sections.append("")
		sections.append("Code examples:")
		if code:
			for item in code:
				sections.append(
					f"- {item.get('language', 'unknown')} from {item.get('url', '')}: {item.get('context', '')}\n{item.get('snippet', '')}"
				)
		else:
			sections.append("- No code examples found.")
		return "\n".join(sections)

	def _prompt_response(self, request_id: Any, text: str) -> Dict[str, Any]:
		return self._success_response(
			request_id,
			{
				"messages": [
					{
						"role": "user",
						"content": {"type": "text", "text": text},
					}
				]
			},
		)

	def _crawler_status(self) -> Dict[str, bool]:
		return {
			"smart": SMART_CRAWLER_AVAILABLE,
			"selenium": SELENIUM_AVAILABLE,
			"ultrafast": ULTRAFAST_AVAILABLE,
		}

	def _doc_resource_uri(self, url: str) -> str:
		return f"docs://document/{quote(url, safe='')}"

	def _coerce_int(self, value: Any, default: int, minimum: int, maximum: int) -> int:
		try:
			number = int(value)
		except (TypeError, ValueError):
			number = default
		return max(minimum, min(number, maximum))

	def _success_response(self, request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
		response = {"jsonrpc": "2.0", "result": result}
		if request_id is not None:
			response["id"] = request_id
		return response

	def _error_response(self, request_id: Any, code: int, message: str) -> Dict[str, Any]:
		response = {
			"jsonrpc": "2.0",
			"error": {"code": code, "message": message},
		}
		if request_id is not None:
			response["id"] = request_id
		return response


mcp_server = MCPServer()
