import time
import json
import requests
import urllib3
import threading
from queue import Queue
from urllib.parse import urlparse, urljoin, urldefrag
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


class UltraFastCrawler:
    """
    Threaded pipeline crawler — concurrent workers using requests + optional Selenium fallback.
    On Vercel (no Selenium), runs requests-only path with full concurrency.
    """
    def __init__(self, start_url, max_depth=2, max_workers=8):
        self.start_url = start_url.rstrip("/")
        self.max_depth = max_depth
        self.max_workers = max_workers

        parsed = urlparse(self.start_url)
        self.base_domain = parsed.netloc
        self.allowed_prefix = parsed.path.rstrip("/")

        self.visited = set()
        self.data = {}

        self.lock = threading.Lock()
        self.queue = Queue()

        self.driver = None  # lazy selenium

    def clean_url(self, url):
        url, _ = urldefrag(url)
        return url.rstrip("/")

    def is_valid_url(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            return False
        if parsed.netloc != self.base_domain:
            return False

        # Avoid auth/utility pages
        path = parsed.path.lower()
        junk_paths = ['login', 'signin', 'signup', 'register', 'logout', 'password-reset', 'cart', 'checkout', 'telemetry', 'track']
        if any(jp in path for jp in junk_paths):
            return False

        if self.allowed_prefix:
            if not parsed.path.startswith(self.allowed_prefix):
                return False
        return True

    def fetch_requests(self, url):
        try:
            r = requests.get(url, timeout=8, verify=False, headers={
                "User-Agent": "Mozilla/5.0 (compatible; Scrapee/1.0)"
            })
            if r.status_code == 200:
                return r.text
        except Exception:
            return None
        return None

    def needs_selenium(self, html):
        if not html:
            return True
        if len(html) < 1500:
            return True
        if html.count("<script") > 20 and html.count("<p") < 5:
            return True
        return False

    def init_selenium(self):
        if not SELENIUM_AVAILABLE:
            return
        if self.driver is None:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--blink-settings=imagesEnabled=false")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)

    def fetch_selenium(self, url):
        if not SELENIUM_AVAILABLE:
            return None
        self.init_selenium()
        self.driver.get(url)
        time.sleep(1)
        return self.driver.page_source

    def worker(self):
        while True:
            item = self.queue.get()
            if item is None:
                break

            current_url, depth = item
            current_url = self.clean_url(current_url)

            with self.lock:
                if current_url in self.visited or depth > self.max_depth:
                    self.queue.task_done()
                    continue
                self.visited.add(current_url)

            html = self.fetch_requests(current_url)

            # Only upgrade to Selenium if available AND page looks JS-rendered
            if SELENIUM_AVAILABLE and self.needs_selenium(html):
                selenium_html = self.fetch_selenium(current_url)
                if selenium_html:
                    html = selenium_html

            if html:
                with self.lock:
                    self.data[current_url] = html

                soup = BeautifulSoup(html, "html.parser")
                for tag in soup.find_all("a", href=True):
                    href = tag["href"]
                    full_url = urljoin(current_url, href)
                    full_url = self.clean_url(full_url)
                    if self.is_valid_url(full_url):
                        with self.lock:
                            if full_url not in self.visited:
                                self.queue.put((full_url, depth + 1))

            self.queue.task_done()

    def crawl(self):
        self.queue.put((self.start_url, 0))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for _ in range(self.max_workers):
                executor.submit(self.worker)
            self.queue.join()
            for _ in range(self.max_workers):
                self.queue.put(None)

        if self.driver:
            self.driver.quit()

        return self.data
