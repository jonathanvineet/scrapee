import time
import json
import requests
from collections import deque
from urllib.parse import urlparse, urljoin, urldefrag

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


class SmartCrawler:
    def __init__(self, start_url, max_depth=2):
        self.start_url = start_url.rstrip("/")
        self.max_depth = max_depth

        parsed = urlparse(self.start_url)
        self.base_domain = parsed.netloc
        self.allowed_prefix = parsed.path.rstrip("/")

        self.visited = set()
        self.data = {}

        self.driver = None  # lazy load selenium only if needed

    # ----------------------------
    # Utilities
    # ----------------------------

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

    # ----------------------------
    # Intelligent Page Fetch
    # ----------------------------

    def fetch_with_requests(self, url):
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                return r.text
        except:
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

    # ----------------------------
    # Crawl Logic
    # ----------------------------

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

            print(f"Scraping: {current_url}")
            self.visited.add(current_url)

            html = self.fetch_with_requests(current_url)

            if self.needs_selenium(html):
                print("  → Switching to Selenium")
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


if __name__ == "__main__":
    start_url = input("Enter starting URL: ").strip()

    crawler = SmartCrawler(start_url=start_url, max_depth=2)
    result = crawler.crawl()

    print(f"\nTotal pages scraped: {len(result)}")

    with open("scraped_output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("Saved to scraped_output.json")