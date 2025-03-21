"""
Core email extraction logic for the Email Extractor.
"""

import asyncio
import time
from urllib.parse import urlparse

from email_extractor.config import MAX_CONTACT_PAGES, GLOBAL_TIMEOUT, VERIFY_MX_RECORDS
from email_extractor.utils import logger, normalize_url, is_valid_url, verify_mx_record, get_email_domain

class EmailExtractor:
    """Handles the email extraction process."""
    
    def __init__(self, http_handler, playwright_handler, crawler):
        """
        Initialize the email extractor.
        
        Args:
            http_handler: The HTTP handler for making requests
            playwright_handler: The Playwright handler for JavaScript-heavy sites
            crawler: The crawler for finding contact pages
        """
        self.http_handler = http_handler
        self.playwright_handler = playwright_handler
        self.crawler = crawler
        self.start_time = None
        self.extracted_emails = set()
    
    def _is_timeout_reached(self):
        """Check if the global timeout has been reached."""
        if not self.start_time:
            return False
        
        elapsed = time.time() - self.start_time
        return elapsed >= GLOBAL_TIMEOUT
    
    def _normalize_input_url(self, url):
        """
        Normalize the input URL.
        
        Args:
            url (str): The URL to normalize
            
        Returns:
            str: The normalized URL or None if invalid
        """
        # Add http:// if no scheme is provided
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Validate the URL
        if not is_valid_url(url):
            logger.error(f"Invalid URL: {url}")
            return None
        
        # Normalize the URL
        return normalize_url(url)
    
    async def extract_emails_from_url(self, url):
        """
        Extract emails from a URL and its contact pages.
        
        Args:
            url (str): The URL to extract emails from
            
        Returns:
            set: Set of extracted email addresses
        """
        self.start_time = time.time()
        self.extracted_emails = set()
        
        # Normalize the input URL
        normalized_url = self._normalize_input_url(url)
        if not normalized_url:
            return self.extracted_emails
        
        logger.info(f"Starting email extraction for: {normalized_url}")
        
        # Step 1: Try to extract emails from the homepage using HTTP
        homepage_emails = self.http_handler.extract_emails_from_page(normalized_url)
        self._add_emails(homepage_emails)
        
        # If we found emails, we're done - no need for Playwright
        if self.extracted_emails:
            logger.info(f"Found {len(self.extracted_emails)} emails on homepage using HTTP")
            return self.extracted_emails
        
        # Step 2: Find contact pages
        contact_pages = await self.crawler.find_contact_pages(normalized_url)
        
        # Step 3: Extract emails from contact pages using HTTP
        for contact_url in contact_pages:
            if self._is_timeout_reached():
                logger.warning("Global timeout reached, stopping extraction")
                break
                
            contact_emails = self.http_handler.extract_emails_from_page(contact_url)
            self._add_emails(contact_emails)
            
            # If we found emails, we can stop - no need for Playwright
            if self.extracted_emails:
                logger.info(f"Found {len(self.extracted_emails)} emails on contact pages using HTTP")
                return self.extracted_emails
        
        # Step 4: If no emails found and not timed out, try Playwright on homepage
        if not self.extracted_emails and not self._is_timeout_reached():
            logger.info("No emails found with HTTP, trying Playwright on homepage")
            
            # Try homepage with Playwright
            homepage_emails_pw = await self.playwright_handler.extract_emails_from_page(normalized_url)
            self._add_emails(homepage_emails_pw)
            
            # If we found emails, we're done
            if self.extracted_emails:
                logger.info(f"Found {len(self.extracted_emails)} emails on homepage using Playwright")
                return self.extracted_emails
            
            # Step 5: If still no emails, try contact pages with Playwright
            logger.info("No emails found on homepage with Playwright, trying contact pages")
            for contact_url in contact_pages:
                if self._is_timeout_reached():
                    logger.warning("Global timeout reached, stopping extraction")
                    break
                    
                contact_emails_pw = await self.playwright_handler.extract_emails_from_page(contact_url)
                self._add_emails(contact_emails_pw)
                
                # If we found emails, we can stop
                if self.extracted_emails:
                    logger.info(f"Found {len(self.extracted_emails)} emails on contact pages using Playwright")
                    return self.extracted_emails
        
        # If we reached here, we either found no emails or hit the timeout
        if self._is_timeout_reached():
            logger.warning("Email extraction stopped due to timeout")
        else:
            logger.info("No emails found after trying all methods")
        
        logger.info(f"Extraction complete. Found {len(self.extracted_emails)} emails")
        return self.extracted_emails
    
    def _add_emails(self, emails):
        """
        Add emails to the extracted emails set after verifying MX records.
        
        Args:
            emails (list): List of emails to add
        """
        if not emails:
            return
            
        for email in emails:
            # Skip if email is already in the set
            if email in self.extracted_emails:
                continue
                
            # Verify MX records if enabled
            if VERIFY_MX_RECORDS:
                domain = get_email_domain(email)
                if domain and verify_mx_record(domain):
                    self.extracted_emails.add(email)
                    logger.info(f"Added email with valid MX record: {email}")
                else:
                    logger.warning(f"Skipped email with invalid MX record: {email}")
            else:
                # Add email without MX verification
                self.extracted_emails.add(email)