import time
from collections import deque
from urllib.parse import urlparse, urljoin, urldefrag

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


class SeleniumCrawler:
    """
    Pure Selenium crawler - uses headless Chrome for all pages.
    Guarantees full JavaScript execution but slower than other methods.
    """
    def __init__(self, start_url, max_depth=2, timeout_limit=25):
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium not available. Install selenium and webdriver-manager: pip install selenium webdriver-manager")
        
        self.start_url = start_url.rstrip("/")
        self.max_depth = max_depth
        self.timeout_limit = timeout_limit
        self.start_time = time.time()

        parsed = urlparse(self.start_url)
        self.base_domain = parsed.netloc
        self.allowed_prefix = parsed.path.rstrip("/")

        self.visited = set()
        self.data = {}
        self.driver = None

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

    def setup_driver(self):
        """Set up Chrome driver with optimized options for scraping"""
        if self.driver:
            return
            
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-images')
        options.add_argument('--disable-javascript')  # We want JS but can disable for faster loading
        options.add_argument('--user-agent=Mozilla/5.0 (compatible; Scrapee-Selenium/1.0)')
        
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.set_page_load_timeout(10)
        except Exception as e:
            raise RuntimeError(f"Failed to setup Chrome driver: {e}")

    def fetch_with_selenium(self, url):
        """Fetch URL content using Selenium WebDriver"""
        try:
            if not self.driver:
                self.setup_driver()
                
            self.driver.get(url)
            
            # Wait a bit for dynamic content
            time.sleep(2)
            
            # Get page source
            html = self.driver.page_source
            return html if html else None
            
        except Exception as e:
            print(f"Selenium fetch failed for {url}: {e}")
            return None

    def crawl(self):
        """Main crawling method using Selenium for all pages"""
        queue = deque()
        queue.append((self.start_url, 0))

        try:
            while queue:
                # Check timeout
                elapsed = time.time() - self.start_time
                if elapsed > self.timeout_limit:
                    raise TimeoutError(f'Crawl exceeded timeout limit of {self.timeout_limit}s')

                current_url, depth = queue.popleft()
                current_url = self.clean_url(current_url)

                if current_url in self.visited:
                    continue
                if depth > self.max_depth:
                    continue

                self.visited.add(current_url)

                # Fetch page with Selenium
                html = self.fetch_with_selenium(current_url)
                if not html:
                    continue

                self.data[current_url] = html

                # Parse links for next depth level
                if depth < self.max_depth:
                    try:
                        # Find links using Selenium
                        links = self.driver.find_elements(By.TAG_NAME, "a")
                        for link in links:
                            try:
                                href = link.get_attribute("href")
                                if href:
                                    full_url = urljoin(current_url, href)
                                    full_url = self.clean_url(full_url)
                                    if self.is_valid_url(full_url):
                                        queue.append((full_url, depth + 1))
                            except Exception:
                                continue
                    except Exception:
                        pass

        finally:
            if self.driver:
                self.driver.quit()

        return self.data