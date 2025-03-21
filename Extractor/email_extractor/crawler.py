"""
Crawler module for the Email Extractor.
"""

import asyncio
from urllib.parse import urlparse
import time

from email_extractor.config import (
    MAX_CONTACT_PAGES, MAX_PAGES_PER_DOMAIN, GLOBAL_TIMEOUT,
    CONTACT_PAGE_SEARCH_TIMEOUT
)
from email_extractor.utils import normalize_url, is_same_domain, logger

class Crawler:
    """Handles the crawling logic for finding contact pages."""
    
    def __init__(self, http_handler, playwright_handler=None):
        """
        Initialize the crawler.
        
        Args:
            http_handler: The HTTP handler for making requests
            playwright_handler: Optional Playwright handler for JavaScript-heavy sites
        """
        self.http_handler = http_handler
        self.playwright_handler = playwright_handler
        self.visited_urls = set()
        self.contact_pages = []
        self.start_time = None
    
    def _is_timeout_reached(self):
        """Check if the global timeout has been reached."""
        if not self.start_time:
            return False
        
        elapsed = time.time() - self.start_time
        return elapsed >= GLOBAL_TIMEOUT
    
    def _should_visit_url(self, url, base_url):
        """
        Determine if a URL should be visited.
        
        Args:
            url (str): The URL to check
            base_url (str): The base URL of the website
            
        Returns:
            bool: True if the URL should be visited, False otherwise
        """
        # Skip if already visited
        if url in self.visited_urls:
            return False
        
        # Skip if not the same domain
        if not is_same_domain(url, base_url):
            return False
        
        # Skip if we've reached the maximum number of pages
        if len(self.visited_urls) >= MAX_PAGES_PER_DOMAIN:
            return False
        
        # Skip if timeout reached
        if self._is_timeout_reached():
            return False
        
        return True
    
    async def find_contact_pages(self, url):
        """
        Find contact pages starting from the given URL with timeout protection.
        
        Args:
            url (str): The starting URL
            
        Returns:
            list: List of contact page URLs
        """
        try:
            # Create a task with timeout
            crawl_task = asyncio.create_task(self._find_contact_pages_impl(url))
            try:
                return await asyncio.wait_for(crawl_task, timeout=CONTACT_PAGE_SEARCH_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning(f"Contact page search timed out for {url}")
                return []
        except Exception as e:
            logger.error(f"Error finding contact pages: {str(e)}")
            return []

    async def _find_contact_pages_impl(self, url):
        """Implementation of contact page finding with proper error handling."""
        self.start_time = time.time()
        self.visited_urls = set()
        self.contact_pages = []
        
        # Start with the homepage
        await self._crawl_for_contact_pages(url, url)
        
        # Limit to the top MAX_CONTACT_PAGES contact pages
        return self.contact_pages[:MAX_CONTACT_PAGES]
    
    async def _crawl_for_contact_pages(self, url, base_url):
        """
        Recursively crawl for contact pages.
        
        Args:
            url (str): The current URL to crawl
            base_url (str): The base URL of the website
        """
        # Check if we should stop crawling
        if self._is_timeout_reached() or len(self.contact_pages) >= MAX_CONTACT_PAGES:
            return
        
        # Skip if we shouldn't visit this URL
        if not self._should_visit_url(url, base_url):
            return
        
        # Mark as visited
        self.visited_urls.add(url)
        
        # Try HTTP request first
        html_text, soup = self.http_handler.fetch_url(url)
        
        # If HTTP request failed and Playwright is available, try with Playwright
        if (not html_text or not soup) and self.playwright_handler:
            success, html_content, soup = await self.playwright_handler.navigate_to_url(url)
            if not success or not soup:
                return
        
        # If we still don't have a soup, return
        if not soup:
            return
        
        # Find contact pages from the current page
        if self.playwright_handler and hasattr(self.playwright_handler, 'page'):
            # Use Playwright if available
            contact_urls = await self.playwright_handler.find_contact_pages(base_url)
        else:
            # Fallback to HTTP handler
            contact_urls = self.http_handler.find_contact_pages(base_url, soup)
        
        # Add contact pages to the list
        for contact_url in contact_urls:
            if contact_url not in self.contact_pages and len(self.contact_pages) < MAX_CONTACT_PAGES:
                self.contact_pages.append(contact_url)
        
        # If we have enough contact pages, return
        if len(self.contact_pages) >= MAX_CONTACT_PAGES:
            return
        
        # If we've reached the timeout, return
        if self._is_timeout_reached():
            return