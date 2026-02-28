import time
import json
from collections import deque
from urllib.parse import urlparse, urljoin, urldefrag

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


class SeleniumCrawler:
    def __init__(self, start_url, max_depth=2):
        self.start_url = start_url.rstrip("/")
        self.max_depth = max_depth

        parsed = urlparse(self.start_url)
        self.base_domain = parsed.netloc
        self.allowed_prefix = parsed.path.rstrip("/")

        self.visited = set()
        self.data = {}

        # Chrome Options
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

        # Let webdriver-manager handle driver version automatically
        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)

    def clean_url(self, url):
        url, _ = urldefrag(url)  # remove #fragment
        return url.rstrip("/")

    def is_valid_url(self, url):
        parsed = urlparse(url)

        if parsed.scheme not in ["http", "https"]:
            return False

        if parsed.netloc != self.base_domain:
            return False

        clean_path = parsed.path.rstrip("/")

        if self.allowed_prefix:
            if not clean_path.startswith(self.allowed_prefix):
                return False

        return True

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

            try:
                self.driver.get(current_url)
                time.sleep(2)
            except Exception as e:
                print(f"Failed: {current_url} | {e}")
                continue

            self.data[current_url] = self.driver.page_source

            links = self.driver.find_elements("tag name", "a")

            for link in links:
                href = link.get_attribute("href")
                if not href:
                    continue

                full_url = urljoin(current_url, href)
                full_url = self.clean_url(full_url)

                if self.is_valid_url(full_url):
                    queue.append((full_url, depth + 1))

        self.driver.quit()
        return self.data


if __name__ == "__main__":
    start_url = input("Enter starting URL: ").strip()

    crawler = SeleniumCrawler(start_url=start_url, max_depth=2)
    result = crawler.crawl()

    print(f"\nTotal pages scraped: {len(result)}")

    with open("scraped_output.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("Saved to scraped_output.json")