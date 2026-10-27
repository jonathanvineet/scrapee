"""Regression tests for retrieval, the index API and the CLI.

Run from the repo root:  backend/venv/bin/python -m unittest discover backend/tests
Uses a throwaway SQLite file; never touches backend/db/docs.db or the network.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="scrapee-test-")
os.environ["SCRAPEE_SQLITE_PATH"] = os.path.join(_TMP, "docs.db")
os.environ["SCRAPEE_DISABLE_VECTORS"] = "1"
os.environ.pop("SCRAPEE_BOOTSTRAP_DOCS", None)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "cli"))

import mcp_engine  # noqa: E402
from app import app  # noqa: E402
import scrapee  # noqa: E402

TRIGGERED = []
mcp_engine.trigger_background_scrape = lambda query, urls, store=None: TRIGGERED.append((query, urls)) or True

STATE_DOC = (
    "State: a component's memory. Components often need to change what's on the screen as a "
    "result of an interaction. Call useState at the top level of your component to declare a "
    "state variable. The useState hook returns a pair: the current state and a setter function."
)
EFFECT_DOC = (
    "Synchronizing with effects. Some components need to synchronize with external systems. "
    "Effects let you run some code after rendering. Return a cleanup function from useEffect so "
    "React can stop synchronizing when the component unmounts or before the effect runs again."
)
PATH_DOC = (
    "Path parameters. You can declare path parameters or variables with the same syntax used by "
    "Python format strings. The value of the path parameter item_id will be passed to your "
    "function as the argument item_id, and FastAPI validates its declared type for you."
)
CONTAINER_DOC = (
    "Docker containers and queries. A container is a runnable instance of an image. You can list "
    "running containers and run queries against the engine API to inspect each container's state, "
    "network settings and mounted volumes from the command line or an SDK."
)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = mcp_engine.mcp_server
        cls.store = cls.server.store
        cls.store.delete_all_documents()
        cls.store.save_doc("https://react.dev/learn/state", STATE_DOC, {"title": "State: a component's memory"},
                           code_blocks=[{"snippet": "const [index, setIndex] = useState(0);", "language": "js"}])
        cls.store.save_doc("https://react.dev/learn/effects", EFFECT_DOC, {"title": "Synchronizing with Effects¶"})
        cls.store.save_doc("https://fastapi.tiangolo.com/tutorial/path-params/", PATH_DOC, {"title": "Path Parameters"})
        cls.store.save_doc("https://docs.docker.com/engine/containers/", CONTAINER_DOC, {"title": "Containers"})
        cls.server.cache.clear()


class RetrievalTests(Base):
    def test_get_context_ranks_the_matching_page_first_and_keeps_case(self):
        res = self.server._tool_get_context({"query": "useState hook"})
        self.assertEqual(res["status"], "ready")
        self.assertEqual(res["sources"][0], "https://react.dev/learn/state")
        self.assertIn("useState", res["context"])  # not lowercased
        self.assertIn("[SOURCE: https://react.dev/learn/state]", res["context"])
        self.assertIn("setIndex", res["context"])  # its code block came along

    def test_unmatched_query_learns_instead_of_returning_unrelated_pages(self):
        TRIGGERED.clear()
        res = self.server._tool_get_context({"query": "tailwind container queries"})
        self.assertEqual(res["status"], "learning")
        self.assertEqual(res["sources"], [])
        self.assertEqual(TRIGGERED[0][1], ["https://tailwindcss.com/docs"])

    def test_unknown_topic_is_not_found_and_crawls_nothing(self):
        TRIGGERED.clear()
        res = self.server._tool_get_context({"query": "zygomorphic flux capacitor"})
        self.assertEqual(res["status"], "not_found")
        self.assertEqual(TRIGGERED, [])

    def test_search_returns_nothing_rather_than_recent_docs(self):
        self.assertEqual(self.store.search_docs("kubernetes ingress annotations"), [])

    def test_titles_drop_permalink_pilcrows(self):
        doc = self.store.get_doc("https://react.dev/learn/effects")
        self.assertEqual(doc["title"], "Synchronizing with Effects")

    def test_doc_domain_hints_match_whole_words(self):
        self.assertEqual(self.server._detect_doc_domain("mongo aggregation"), None)
        self.assertEqual(self.server._detect_doc_domain("go generics"), "https://go.dev/doc/")
        self.assertEqual(self.server._detect_doc_domain("tailwindcss grid"), "https://tailwindcss.com/docs")

    def test_cache_honours_per_entry_ttl(self):
        self.server.cache.set("k", 1, ttl=60)
        self.assertEqual(self.server.cache.get("k"), 1)

    def test_tools_call_get_context_over_json_rpc(self):
        res = self.server.handle_request({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                          "params": {"name": "get_context", "arguments": {"query": "path parameters"}}})
        self.assertNotIn("error", res)
        self.assertEqual(res["result"]["structuredContent"]["sources"][0],
                         "https://fastapi.tiangolo.com/tutorial/path-params/")


class ConcurrencyTests(Base):
    def test_threads_get_their_own_connection_and_can_read_while_one_writes(self):
        import threading
        errors = []

        def reader():
            try:
                for _ in range(60):
                    self.store.search_docs("useState hook")
                    self.store.get_stats()
                    self.store.list_sources()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def writer():
            try:
                for i in range(30):
                    self.store.save_doc(f"https://threads.dev/{i}", PATH_DOC + f" page {i}", {"title": f"t{i}"})
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(8)] + [threading.Thread(target=writer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertIsNot(self.store.conn, self._other_thread_conn())
        self.store.delete_domain_documents("threads.dev")

    def _other_thread_conn(self):
        import threading
        box = []
        t = threading.Thread(target=lambda: box.append(self.store.conn))
        t.start()
        t.join()
        return box[0]


class ApiTests(Base):
    def setUp(self):
        self.client = app.test_client()

    def test_sources_lists_domains_with_counts(self):
        data = self.client.get("/api/sources").get_json()
        by_domain = {s["domain"]: s for s in data["sources"]}
        self.assertEqual(by_domain["react.dev"]["docs"], 2)
        self.assertEqual(by_domain["react.dev"]["code_blocks"], 1)

    def test_context_requires_a_query(self):
        self.assertEqual(self.client.post("/api/context", json={}).status_code, 400)

    def test_reset_requires_confirmation(self):
        self.assertEqual(self.client.post("/api/reset", json={}).status_code, 400)

    def test_delete_source_removes_its_fts_rows(self):
        self.store.save_doc("https://example-delete.dev/a", PATH_DOC.replace("FastAPI", "Zebra"), {"title": "a"})
        res = self.client.delete("/api/sources/example-delete.dev").get_json()
        self.assertEqual(res["removed"], 1)
        orphans = self.store.conn.execute(
            "SELECT count(*) FROM docs_fts WHERE rowid NOT IN (SELECT id FROM docs)").fetchone()[0]
        self.assertEqual(orphans, 0)


class CliTests(unittest.TestCase):
    def test_detect_project_reads_every_dependency(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "package.json").write_text(json.dumps(
                {"dependencies": {"next": "14", "react": "18"}, "devDependencies": {"tailwindcss": "3"}}))
            Path(d, "requirements.txt").write_text("fastapi==0.110\nuvicorn\n")
            found = scrapee.detect_project(d)
        for key in ("react", "next", "tailwind", "nodejs", "fastapi", "python"):
            self.assertIn(key, found)

    def test_extract_imports_skips_relative_and_handles_scopes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "page.js")
            f.write_text("import Link from 'next/link'\nimport { x } from './local'\n"
                         "import font from '@next/font/google'\nconst e = require('express')\n")
            p = Path(d, "main.py")
            p.write_text("from fastapi.security import OAuth2\nimport flask\n")
            imports = scrapee.extract_imports([str(f), str(p)])
        self.assertEqual(set(imports), {"next", "@next", "express", "fastapi", "flask"})

    def test_help_exits_without_starting_the_repl(self):
        self.assertEqual(scrapee.main(["--help"]), 0)


if __name__ == "__main__":
    unittest.main()
