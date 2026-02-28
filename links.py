import time
from urllib.parse import urljoin, urlparse, urldefrag
from collections import deque

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


class SeleniumCrawler:
    def __init__(self, start_url, max_depth=2):
        self.start_url = start_url
        self.base_domain = urlparse(start_url).netloc
        self.max_depth = max_depth

        self.visited = set()
        self.data = {}

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")

        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )

    def is_valid_url(self, url):
        parsed = urlparse(url)

        # Same domain only
        if parsed.netloc != self.base_domain:
            return False

        # Avoid mailto, javascript links
        if parsed.scheme not in ["http", "https"]:
            return False

        # Avoid login/signup keywords
        blocked_keywords = ["login", "signup", "password", "privacy", "terms"]
        if any(word in parsed.path.lower() for word in blocked_keywords):
            return False

        return True

    def clean_url(self, url):
        url, _ = urldefrag(url)  # remove #fragment
        return url.rstrip("/")

    def crawl(self):
        queue = deque()
        queue.append((self.start_url, 0))

        while queue:
            current_url, depth = queue.popleft()

            if depth > self.max_depth:
                continue

            current_url = self.clean_url(current_url)

            if current_url in self.visited:
                continue

            print(f"Scraping: {current_url}")
            self.visited.add(current_url)

            try:
                self.driver.get(current_url)
                time.sleep(2)  # wait for JS rendering
            except:
                continue

            # Store page content
            self.data[current_url] = self.driver.page_source

            # Extract links
            elements = self.driver.find_elements("tag name", "a")

            for element in elements:
                href = element.get_attribute("href")
                if not href:
                    continue

                full_url = urljoin(current_url, href)
                full_url = self.clean_url(full_url)

                if self.is_valid_url(full_url):
                    queue.append((full_url, depth + 1))

        self.driver.quit()
        return self.data


if __name__ == "__main__":
    start = "https://github.com/jonathanvineet?tab=repositories"
    crawler = SeleniumCrawler(start_url=start, max_depth=2)
    result = crawler.crawl()

    print(f"\nTotal pages scraped: {len(result)}")