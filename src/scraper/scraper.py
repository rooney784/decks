import os
import logging
import time
from urllib.parse import urljoin
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    WebDriverException, TimeoutException, NoSuchElementException
)
from webdriver_manager.chrome import ChromeDriverManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler('scraper.log')],
)
logger = logging.getLogger(__name__)

load_dotenv()
URL_TO_SCRAPE = os.getenv("URL_TO_SCRAPE")
EXCLUDE_TERMS = [term.strip().lower() for term in os.getenv("EXCLUDE_TERMS", "").split(",") if term.strip()]

def filter_links(links):
    """Filter links based on exclusion terms and digit count"""
    if not links:
        return []
    
    # Get filter criteria from environment
    filter_enabled = os.getenv("FILTER_LINKS", "true").lower() == "true"
    required_digits = int(os.getenv("REQUIRED_DIGITS", "19"))
    
    if not filter_enabled or not EXCLUDE_TERMS:
        logger.info("Link filtering is disabled or no exclude terms defined")
        return links
    
    filtered = []
    for link in links:
        link_lower = link.lower()
        
        # Check digit count
        digit_count = sum(char.isdigit() for char in link)
        
        # Check exclusion criteria
        if (digit_count == required_digits and 
            not any(term in link_lower for term in EXCLUDE_TERMS) and
            'pro.twitter.com' not in link_lower):
            filtered.append(link)
    
    logger.info(f"Filtered {len(links)} links to {len(filtered)} valid links")
    return filtered

def scrape_links():
    links = set()
    log_messages = []

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")

    driver = None
    try:
        logger.info("Starting headless browser")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        log_messages.append("🚀 Headless browser started")

        logger.info(f"Navigating to {URL_TO_SCRAPE}")
        driver.set_page_load_timeout(30)
        driver.get(URL_TO_SCRAPE)
        driver.implicitly_wait(10)
        log_messages.append(f"🌐 Loaded {URL_TO_SCRAPE}")

        # Infinite scroll + interact
        scroll_pause = 2
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(scroll_pause)

            # try Load More buttons
            for btn in driver.find_elements(By.XPATH, "//button|//a"):
                text = btn.text.lower()
                if "load more" in text or "show more" in text:
                    try:
                        btn.click()
                        logger.info("Clicked 'Load More'")
                        time.sleep(scroll_pause)
                    except Exception:
                        pass

            new_height = driver.execute_script("return document.body.scrollHeight")
            if not hasattr(scrape_links, "last_height"):
                scrape_links.last_height = new_height
            elif new_height == scrape_links.last_height:
                break
            scrape_links.last_height = new_height

        log_messages.append("✅ Finished scrolling + interactions")

        # extract links from iframes
        def extract_from_context():
            for a in driver.find_elements(By.TAG_NAME, "a"):
                href = a.get_attribute("href")
                if href:
                    links.add(urljoin(URL_TO_SCRAPE, href))
        extract_from_context()

        # Iterate iframes
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        logger.info(f"Found {len(iframes)} iframes")
        for idx, frame in enumerate(iframes):
            try:
                driver.switch_to.frame(frame)
                extract_from_context()
                driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()

        log_messages.append(f"🔗 Collected {len(links)} unique links")
        logger.info(f"Collected {len(links)} unique links")

        # Filter links
        filtered_links = filter_links(list(links))
        log_messages.append(f"🔍 Filtered to {len(filtered_links)} valid links")
        
        # save screenshot
        os.makedirs("screenshots", exist_ok=True)
        screenshot_path = "screenshots/scrape_result.png"
        driver.save_screenshot(screenshot_path)
        log_messages.append(f"📸 Screenshot saved to {screenshot_path}")

        return filtered_links, log_messages, screenshot_path

    except TimeoutException:
        em = "❌ Page load timed out."
        logger.error(em); log_messages.append(em)
        return [], log_messages, None
    except WebDriverException as e:
        em = f"❌ Browser error: {e}"
        logger.error(em); log_messages.append(em)
        return [], log_messages, None
    finally:
        if driver:
            driver.quit()
            log_messages.append("🔌 Browser closed")

if __name__ == "__main__":
    lnks, logs, shot = scrape_links()
    print(f"Extracted {len(lnks)} links")
    for l in lnks:
        print(l)
    print("Logs:")
    for e in logs:
        print(e)