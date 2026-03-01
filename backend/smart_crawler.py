import time
import json
import requests
from collections import deque
from urllib.parse import urlparse, urljoin, urldefrag

from bs4 import BeautifulSoup

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


class SmartCrawler:
    """
    Smart crawler — tries requests first, falls back to Selenium for JS-heavy pages.
    On Vercel (no Selenium), runs requests-only path.
    """
    def __init__(self, start_url, max_depth=2):
        self.start_url = start_url.rstrip("/")
        self.max_depth = max_depth

        parsed = urlparse(self.start_url)
        self.base_domain = parsed.netloc
        self.allowed_prefix = parsed.path.rstrip("/")

        self.visited = set()
        self.data = {}

        self.driver = None  # lazy load

    def clean_url(self, url):
        url, _ = urldefrag(url)
        return url.rstrip("/")

    def is_valid_url(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            return False
        if parsed.netloc != self.base_domain:
            return False
        if self.allowed_prefix:
            if not parsed.path.startswith(self.allowed_prefix):
                return False
        return True

    def fetch_with_requests(self, url):
        try:
            r = requests.get(url, timeout=8, headers={
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
        if len(html) < 2000:
            return True
        if '<div id="root"></div>' in html:
            return True
        if html.count("<script") > 20 and html.count("<p") < 5:
            return True
        return False

    def fetch_with_selenium(self, url):
        if not SELENIUM_AVAILABLE:
            return None
        if self.driver is None:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--blink-settings=imagesEnabled=false")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.get(url)
        time.sleep(1)
        return self.driver.page_source

    def crawl(self):
        queue = deque()
        queue.append((self.start_url, 0))

        while queue:
            current_url, depth = queue.popleft()
            current_url = self.clean_url(current_url)

            if current_url in self.visited:
                continue
            if depth > self.max_depth:
                continue

            self.visited.add(current_url)

            html = self.fetch_with_requests(current_url)

            if self.needs_selenium(html):
                html = self.fetch_with_selenium(current_url)

            if not html:
                continue

            self.data[current_url] = html

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                full_url = urljoin(current_url, href)
                full_url = self.clean_url(full_url)
                if self.is_valid_url(full_url):
                    queue.append((full_url, depth + 1))

        if self.driver:
            self.driver.quit()

        return self.data
