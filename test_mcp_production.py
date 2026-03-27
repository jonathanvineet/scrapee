#!/usr/bin/env python3
"""End-to-end MCP protocol validation for the production stdio server."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List

from mcp_server.protocol import MCPProtocolServer


@dataclass
class TestResult:
    name: str
    passed: bool
    details: str = ""


class MCPFlowTests:
    def __init__(self) -> None:
        fd, db_path = tempfile.mkstemp(prefix="scrapee-mcp-", suffix=".db")
        os.close(fd)
        self.db_path = db_path
        self.server = MCPProtocolServer(db_path=db_path)
        self.seed_document_uri = ""
        self.seed_code_uri = ""
        self.results: List[TestResult] = []

    def run(self) -> int:
        self._seed()
        self._test_initialize()
        self._test_tools_list()
        self._test_search_docs_then_read_resource()
        self._test_search_code_then_read_resource()
        self._test_invalid_method()
        self._print_summary()
        self._print_example_flow()
        self.server.store.close()
        os.remove(self.db_path)
        return 0 if all(result.passed for result in self.results) else 1

    def _seed(self) -> None:
        saved = self.server.store.upsert_document(
            uri="docs://react/reference/hooks",
            source_url="https://react.dev/reference/react",
            title="React Hooks Reference",
            content=(
                "React hooks let you use state and lifecycle APIs in function components. "
                "useEffect is commonly used for side effects, data fetching, and subscriptions."
            ),
            metadata={"topic": "react-hooks"},
            chunks=[
                "React hooks let you use state and lifecycle APIs in function components.",
                "useEffect is commonly used for side effects, data fetching, and subscriptions.",
            ],
            code_blocks=[
                {
                    "language": "javascript",
                    "snippet": (
                        "import { useEffect, useState } from 'react';\n\n"
                        "export function Example() {\n"
                        "  const [count, setCount] = useState(0);\n"
                        "  useEffect(() => {\n"
                        "    document.title = `Count: ${count}`;\n"
                        "  }, [count]);\n"
                        "  return <button onClick={() => setCount(count + 1)}>{count}</button>;\n"
                        "}"
                    ),
                    "context": "Updating document title with useEffect",
                    "line_start": 1,
                }
            ],
        )
        self.seed_document_uri = str(saved["uri"])
        self.seed_code_uri = str(saved["code_uris"][0])

    def _call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.server.handle_envelope(payload)
        if response is None or isinstance(response, list):
            raise AssertionError("Expected a single JSON-RPC response object")
        return response

    def _record(self, name: str, passed: bool, details: str = "") -> None:
        self.results.append(TestResult(name=name, passed=passed, details=details))

    def _test_initialize(self) -> None:
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        response = self._call(request)
        passed = (
            response.get("jsonrpc") == "2.0"
            and response.get("id") == 1
            and response.get("result", {}).get("protocolVersion") == "2024-11-05"
            and "tools" in response.get("result", {}).get("capabilities", {})
        )
        self._record("initialize", passed, json.dumps(response, ensure_ascii=False))

    def _test_tools_list(self) -> None:
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        response = self._call(request)
        names = [tool["name"] for tool in response.get("result", {}).get("tools", [])]
        required = {"search_docs", "get_document", "scrape_url", "search_code"}
        passed = required.issubset(set(names))
        self._record("tools/list", passed, f"tools={names}")

    def _test_search_docs_then_read_resource(self) -> None:
        search_request = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "search_docs", "arguments": {"query": "react hooks useEffect", "limit": 3}},
        }
        search_response = self._call(search_request)
        documents = search_response.get("result", {}).get("structuredContent", {}).get("documents", [])
        found_uri = documents[0]["uri"] if documents else ""
        read_request = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/read",
            "params": {"uri": found_uri or self.seed_document_uri},
        }
        read_response = self._call(read_request)
        content = read_response.get("result", {}).get("contents", [{}])[0].get("text", "")
        passed = bool(documents) and "useEffect" in content
        self._record("search_docs -> resources/read", passed, f"uri={found_uri}")

    def _test_search_code_then_read_resource(self) -> None:
        search_request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "search_code", "arguments": {"query": "useEffect", "limit": 3}},
        }
        search_response = self._call(search_request)
        matches = search_response.get("result", {}).get("structuredContent", {}).get("matches", [])
        code_uri = matches[0]["uri"] if matches else self.seed_code_uri
        read_request = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "resources/read",
            "params": {"uri": code_uri},
        }
        read_response = self._call(read_request)
        snippet_text = read_response.get("result", {}).get("contents", [{}])[0].get("text", "")
        passed = bool(matches) and "useEffect" in snippet_text
        self._record("search_code -> resources/read", passed, f"uri={code_uri}")

    def _test_invalid_method(self) -> None:
        request = {"jsonrpc": "2.0", "id": 7, "method": "totally/unknown", "params": {}}
        response = self._call(request)
        passed = response.get("error", {}).get("code") == -32601
        self._record("invalid method", passed, json.dumps(response, ensure_ascii=False))

    def _print_summary(self) -> None:
        passed = sum(1 for result in self.results if result.passed)
        failed = len(self.results) - passed
        print("\nMCP Production Flow Tests")
        print("=" * 60)
        for result in self.results:
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] {result.name}")
            if not result.passed and result.details:
                print(f"       {result.details}")
        print("-" * 60)
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print("=" * 60)

    def _print_example_flow(self) -> None:
        print("\nExample JSON-RPC flow")
        print("=" * 60)
        flow = [
            {"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 101, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 102,
                "method": "tools/call",
                "params": {"name": "search_docs", "arguments": {"query": "react hooks"}},
            },
            {"jsonrpc": "2.0", "id": 103, "method": "resources/read", "params": {"uri": self.seed_document_uri}},
        ]
        for request in flow:
            response = self._call(request)
            print("request:")
            print(json.dumps(request, ensure_ascii=False, indent=2))
            print("response:")
            print(json.dumps(response, ensure_ascii=False, indent=2))
            print("-" * 60)


if __name__ == "__main__":
    tests = MCPFlowTests()
    raise SystemExit(tests.run())
