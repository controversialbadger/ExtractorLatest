"""
Main script for the Email Extractor.
"""

import asyncio
import sys
import signal
import os
import time
from contextlib import asynccontextmanager

from email_extractor.http_handler import HTTPHandler
from email_extractor.playwright_handler import PlaywrightHandler
from email_extractor.crawler import Crawler
from email_extractor.extractor import EmailExtractor
from email_extractor.config import OUTPUT_FILE, GLOBAL_TIMEOUT
from email_extractor.utils import logger

# Global variables for cleanup
extractor = None
playwright_handler = None

def signal_handler(sig, frame):
    """Handle keyboard interrupts."""
    logger.info("Keyboard interrupt detected. Cleaning up...")
    sys.exit(0)

@asynccontextmanager
async def setup_extractor():
    """Set up the email extractor components."""
    global extractor, playwright_handler
    
    # Initialize HTTP handler
    http_handler = HTTPHandler()
    
    # Initialize Playwright handler
    playwright_handler = PlaywrightHandler()
    await playwright_handler.setup_browser()
    
    # Initialize crawler
    crawler = Crawler(http_handler, playwright_handler)
    
    # Initialize extractor
    extractor = EmailExtractor(http_handler, playwright_handler, crawler)
    
    try:
        yield extractor
    finally:
        # Clean up resources
        if playwright_handler:
            await playwright_handler.cleanup()

async def extract_emails_from_url(url):
    """
    Extract emails from a URL with a global timeout.
    
    Args:
        url (str): The URL to extract emails from
    """
    async with setup_extractor() as extractor:
        try:
            # Create a task with a global timeout
            extraction_task = asyncio.create_task(extractor.extract_emails_from_url(url))
            try:
                emails = await asyncio.wait_for(extraction_task, timeout=GLOBAL_TIMEOUT)
                
                # Save emails to output file
                if emails:
                    with open(OUTPUT_FILE, 'a') as f:
                        for email in emails:
                            f.write(f"{email}\n")
                    
                    logger.info(f"Saved {len(emails)} emails to {OUTPUT_FILE}")
                else:
                    logger.warning(f"No emails found for {url}")
            except asyncio.TimeoutError:
                logger.error(f"Global timeout reached for {url}")
                return
        except Exception as e:
            logger.error(f"Error extracting emails from {url}: {str(e)}")

async def main():
    """Main entry point for the Email Extractor."""
    # Set up signal handler for graceful exit
    signal.signal(signal.SIGINT, signal_handler)
    
    # Create output file if it doesn't exist
    if not os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'w') as f:
            pass
    
    logger.info("Email Extractor started")
    logger.info(f"Emails will be saved to {OUTPUT_FILE}")
    
    # Main loop
    while True:
        try:
            # Get URL from user
            url = input("\nEnter a URL (or 'exit' to quit): ").strip()
            
            # Exit if requested
            if url.lower() in ('exit', 'quit', 'q'):
                break
            
            # Skip empty input
            if not url:
                continue
            
            # Create a task with a global timeout
            start_time = time.time()
            try:
                # Extract emails with timeout protection
                await extract_emails_from_url(url)
                
                # Log processing time
                elapsed = time.time() - start_time
                logger.info(f"Processing completed in {elapsed:.2f} seconds")
            except asyncio.TimeoutError:
                logger.error(f"Processing timed out after {GLOBAL_TIMEOUT} seconds")
            except Exception as e:
                logger.error(f"Error processing URL: {str(e)}")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error processing URL: {str(e)}")
    
    logger.info("Email Extractor finished")

if __name__ == "__main__":
    # Run the main function
    asyncio.run(main())