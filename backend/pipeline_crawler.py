import time
import requests
import urllib3
from collections import deque
from urllib.parse import urlparse, urljoin, urldefrag
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

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
    Multi-threaded pipeline crawler - spawns concurrent workers.
    Tries requests first, falls back to Selenium for JS-heavy pages.
    Optimized for speed with multiple parallel workers.
    """
    def __init__(self, start_url, max_depth=2, max_workers=8, timeout_limit=25):
        self.start_url = start_url.rstrip("/")
        self.max_depth = max_depth
        self.max_workers = max_workers
        self.timeout_limit = timeout_limit
        self.start_time = time.time()

        parsed = urlparse(self.start_url)
        self.base_domain = parsed.netloc
        self.allowed_prefix = parsed.path.rstrip("/")

        self.visited = set()
        self.data = {}
        self.visited_lock = Lock()
        self.data_lock = Lock()

    def clean_url(self, url):
        url, _ = urldefrag(url)
        return url.rstrip("/")

    def is_valid_url(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ["http", "https"]:
            return False
        if parsed.netloc != self.base_domain:
            return False
        return True

    def fetch_with_requests(self, url):
        """Fast HTTP request method"""
        try:
            response = requests.get(
                url,
                timeout=6,
                verify=False,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Scrapee-Pipeline/1.0)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                }
            )
            if response.status_code == 200:
                return response.text
        except Exception:
            pass
        return None

    def needs_selenium_fallback(self, html):
        """Determine if page needs Selenium rendering"""
        if not html:
            return True
        if len(html) < 1500:
            return True
        if '<div id="root"></div>' in html:
            return True
        if html.count("<script") > 15 and html.count("<p") < 3:
            return True
        return False

    def fetch_with_selenium_fallback(self, url):
        """Fallback to Selenium if available"""
        if not SELENIUM_AVAILABLE:
            return None
            
        try:
            options = Options()
            options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--disable-images')
            
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(8)
            
            driver.get(url)
            time.sleep(1.5)  # Brief wait for JS
            html = driver.page_source
            driver.quit()
            
            return html
        except Exception:
            return None

    def process_url(self, url_data):
        """Process a single URL - used by thread workers"""
        url, depth = url_data
        
        # Check timeout
        elapsed = time.time() - self.start_time
        if elapsed > self.timeout_limit:
            return None, []
            
        url = self.clean_url(url)
        
        # Thread-safe visited check
        with self.visited_lock:
            if url in self.visited:
                return None, []
            self.visited.add(url)

        # Try requests first
        html = self.fetch_with_requests(url)
        
        # Selenium fallback if needed
        if self.needs_selenium_fallback(html):
            selenium_html = self.fetch_with_selenium_fallback(url)
            if selenium_html:
                html = selenium_html

        if not html:
            return None, []

        # Extract structured data from HTML for ContentFilter
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract title
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text().strip()
        
        # Extract meta description
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag.get("content").strip()
        
        # Extract paragraphs
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text().strip()
            if len(text) > 20:  # Skip very short paragraphs
                paragraphs.append(text)
        
        # Extract headings
        headings = []
        for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
            text = heading.get_text().strip()
            if len(text) > 0:
                headings.append({
                    "level": heading.name,
                    "text": text
                })
        
        # Count links
        links_count = len(soup.find_all("a", href=True))
        
        # Extract code blocks
        code_blocks = []
        for code in soup.find_all(["code", "pre"]):
            snippet = code.get_text().strip()
            if len(snippet) > 0:
                code_blocks.append({
                    "snippet": snippet[:500],  # Limit size
                    "language": ""
                })
        
        # Thread-safe data storage
        with self.data_lock:
            self.data[url] = {
                "url": url,
                "title": title,
                "content": html,
                "meta_description": meta_desc,
                "paragraphs": paragraphs,
                "headings": headings,
                "links_count": links_count,
                "code_blocks": code_blocks,
            }

        # Extract links if we're not at max depth
        found_links = []
        if depth < self.max_depth:
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup.find_all("a", href=True):
                    href = tag["href"]
                    full_url = urljoin(url, href)
                    full_url = self.clean_url(full_url)
                    if self.is_valid_url(full_url):
                        found_links.append((full_url, depth + 1))
            except Exception:
                pass

        return url, found_links

    def crawl(self):
        """Multi-threaded crawling with pipeline processing"""
        queue = deque()
        queue.append((self.start_url, 0))
        processed_urls = set()

        while queue:
            # Check global timeout
            elapsed = time.time() - self.start_time
            if elapsed > self.timeout_limit:
                raise TimeoutError(f'Crawl exceeded timeout limit of {self.timeout_limit}s')

            # Collect batch of URLs to process
            batch = []
            batch_size = min(self.max_workers * 2, len(queue))
            
            for _ in range(batch_size):
                if not queue:
                    break
                url_data = queue.popleft()
                url = self.clean_url(url_data[0])
                if url not in processed_urls:
                    batch.append(url_data)
                    processed_urls.add(url)

            if not batch:
                break

            # Process batch with thread pool
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_url = {
                    executor.submit(self.process_url, url_data): url_data 
                    for url_data in batch
                }
                
                for future in as_completed(future_to_url, timeout=15):
                    try:
                        processed_url, new_links = future.result()
                        if new_links:
                            queue.extend(new_links)
                    except Exception as e:
                        # Skip failed URLs
                        continue

        return self.data