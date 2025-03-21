"""
Playwright handler for the Email Extractor.
"""

import asyncio
import re
import time
from playwright.async_api import async_playwright, TimeoutError
from bs4 import BeautifulSoup, Comment

from email_extractor.config import (
    PLAYWRIGHT_TIMEOUT, HEADLESS, BROWSER_TYPE, 
    SLOW_MO, ACCEPT_COOKIE_KEYWORDS, COOKIE_BANNER_TIMEOUT,
    PAGE_NAVIGATION_TIMEOUT, CONTACT_PAGE_SEARCH_TIMEOUT
)
from email_extractor.utils import (
    get_random_user_agent, extract_emails_from_text, 
    normalize_url, is_likely_contact_page, decode_email_entities,
    extract_obfuscated_emails_from_js, is_valid_email,
    logger
)

class PlaywrightHandler:
    """Handles browser automation using Playwright."""
    
    def __init__(self):
        """Initialize the Playwright handler."""
        self.browser = None
        self.context = None
        self.page = None
        self.visited_urls = set()
    
    async def __aenter__(self):
        """Set up the browser when entering the context manager."""
        await self.setup_browser()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up resources when exiting the context manager."""
        await self.cleanup()
    
    async def setup_browser(self):
        """Set up the Playwright browser."""
        try:
            self.playwright = await async_playwright().start()
            
            # Select browser type
            if BROWSER_TYPE == "firefox":
                browser_engine = self.playwright.firefox
            elif BROWSER_TYPE == "webkit":
                browser_engine = self.playwright.webkit
            else:
                browser_engine = self.playwright.chromium
            
            # Launch browser
            self.browser = await browser_engine.launch(
                headless=HEADLESS,
                slow_mo=SLOW_MO
            )
            
            # Create a context with custom user agent
            self.context = await self.browser.new_context(
                user_agent=get_random_user_agent(),
                viewport={'width': 1280, 'height': 800},
                java_script_enabled=True,
                ignore_https_errors=True
            )
            
            # Set default timeout
            self.context.set_default_timeout(PLAYWRIGHT_TIMEOUT * 1000)  # Convert to ms
            
            # Create a page
            self.page = await self.context.new_page()
            
            # Set up event handlers
            self.page.on("dialog", self._handle_dialog)
            
            logger.info("Playwright browser setup complete")
            return True
            
        except Exception as e:
            logger.error(f"Error setting up Playwright browser: {str(e)}")
            await self.cleanup()
            return False
    
    async def _handle_dialog(self, dialog):
        """Handle dialogs (alerts, confirms, prompts)."""
        logger.info(f"Dismissing dialog: {dialog.message}")
        await dialog.dismiss()
    
    async def _handle_cookie_banners(self):
        """Attempt to handle cookie consent banners with a timeout."""
        try:
            # Set a timeout for cookie banner handling
            cookie_task = asyncio.create_task(self._find_and_click_cookie_button())
            try:
                await asyncio.wait_for(cookie_task, timeout=COOKIE_BANNER_TIMEOUT)
                return True
            except asyncio.TimeoutError:
                logger.debug("Cookie banner handling timed out")
                return False
        except Exception as e:
            logger.warning(f"Error handling cookie banner: {str(e)}")
            return False

    async def _find_and_click_cookie_button(self):
        """Find and click cookie consent buttons."""
        for keyword in ACCEPT_COOKIE_KEYWORDS:
            # Try different selector strategies
            selectors = [
                f"button:has-text('{keyword}')",
                f"button:has-text('{keyword.upper()}')",
                f"button:has-text('{keyword.capitalize()}')",
                f"a:has-text('{keyword}')",
                f"div:has-text('{keyword}'):visible",
                f"[id*='cookie'] button",
                f"[class*='cookie'] button",
                f"[id*='consent'] button",
                f"[class*='consent'] button",
                f"[id*='gdpr'] button",
                f"[class*='gdpr'] button"
            ]
            
            for selector in selectors:
                try:
                    # Reduced timeout for selector waiting and added state option
                    button = await self.page.wait_for_selector(
                        selector, 
                        timeout=1000,
                        state="visible"
                    )
                    if button:
                        try:
                            await button.click()
                            logger.info(f"Clicked cookie consent button: {selector}")
                            await self.page.wait_for_timeout(500)  # Reduced wait time
                            return True
                        except Exception as e:
                            logger.debug(f"Failed to click {selector}: {str(e)}")
                            continue
                except Exception:
                    # Silently continue if selector not found
                    continue
        
        return False
    
    async def navigate_to_url(self, url):
        """
        Navigate to a URL using Playwright.
        
        Args:
            url (str): The URL to navigate to
            
        Returns:
            tuple: (success, html_content, soup)
        """
        if url in self.visited_urls:
            logger.debug(f"Skipping already visited URL: {url}")
            return False, None, None
        
        self.visited_urls.add(url)
        
        try:
            # Navigate to the URL
            logger.info(f"Navigating to URL with Playwright: {url}")
            try:
                # Changed from networkidle to domcontentloaded for faster loading
                response = await self.page.goto(
                    url, 
                    wait_until="domcontentloaded", 
                    timeout=PAGE_NAVIGATION_TIMEOUT * 1000
                )
            except Exception as e:
                logger.warning(f"Navigation error for {url}: {str(e)}, trying to extract content anyway")
                response = None
            
            # Even if navigation times out, try to get content
            if not response:
                try:
                    # Check if we have any content
                    html_content = await self.page.content()
                    if not html_content or len(html_content) < 100:  # Very small content likely means error
                        logger.warning(f"No usable content from {url}")
                        return False, None, None
                except:
                    logger.warning(f"Failed to get content from {url}")
                    return False, None, None
            elif not response.ok:
                logger.warning(f"Failed to navigate to {url}, status: {response.status}")
                return False, None, None
            
            # Handle cookie banners
            await self._handle_cookie_banners()
            
            # Get the page content
            try:
                html_content = await self.page.content()
                
                # Parse with BeautifulSoup
                soup = BeautifulSoup(html_content, 'lxml')
                
                return True, html_content, soup
            except Exception as e:
                logger.error(f"Error getting page content: {str(e)}")
                return False, None, None
            
        except Exception as e:
            logger.error(f"Error navigating to {url} with Playwright: {str(e)}")
            return False, None, None
    
    async def extract_emails_from_page(self, url):
        """
        Extract emails from a web page using Playwright with timeout protection.
        
        Args:
            url (str): The URL to extract emails from
            
        Returns:
            list: List of extracted email addresses
        """
        try:
            # Create a task with timeout
            extraction_task = asyncio.create_task(self._extract_emails_impl(url))
            try:
                return await asyncio.wait_for(extraction_task, timeout=PLAYWRIGHT_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning(f"Email extraction timed out for {url}")
                return []
        except Exception as e:
            logger.error(f"Error in extract_emails_from_page: {str(e)}")
            return []

    async def _extract_emails_impl(self, url):
        """Implementation of email extraction with proper error handling."""
        success, html_content, soup = await self.navigate_to_url(url)
        if not success or not html_content:
            return []
        
        emails = []
        
        # Method 1: Extract from raw HTML (catches obfuscated emails)
        decoded_html = decode_email_entities(html_content)
        raw_emails = extract_emails_from_text(decoded_html)
        emails.extend(raw_emails)
        
        # Method 2: Extract from visible text
        if soup:
            # Get all text from the page
            visible_text = soup.get_text(" ", strip=True)
            text_emails = extract_emails_from_text(visible_text)
            emails.extend(text_emails)
            
            # Method 3: Check mailto links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.startswith('mailto:'):
                    email = href[7:]  # Remove 'mailto:'
                    # Handle additional parameters in mailto links
                    if '?' in email:
                        email = email.split('?')[0]
                    if email and email not in emails:
                        emails.append(email)
            
            # Method 3.1: Extract emails from text content of mailto links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.startswith('mailto:'):
                    # Also check the text content of the link for emails
                    link_text = link.get_text(strip=True)
                    if link_text:
                        text_emails = extract_emails_from_text(link_text)
                        emails.extend(text_emails)
        
            # Method 4: Extract emails from JavaScript code
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string:
                    js_emails = extract_obfuscated_emails_from_js(script.string)
                    emails.extend(js_emails)
            
            # Method 5: Look for inline JavaScript in attributes
            elements_with_js = soup.find_all(attrs={"onclick": True})
            for element in elements_with_js:
                js_emails = extract_obfuscated_emails_from_js(element['onclick'])
                emails.extend(js_emails)
            
            # Method 6: Look for data attributes that might contain emails
            elements_with_data = soup.find_all(lambda tag: any(attr.startswith('data-') for attr in tag.attrs))
            for element in elements_with_data:
                for attr, value in element.attrs.items():
                    if attr.startswith('data-') and isinstance(value, str):
                        data_emails = extract_emails_from_text(value)
                        emails.extend(data_emails)
        
            # Method 7: Search for emails in attributes like title, alt, placeholder
            for element in soup.find_all(attrs={"title": True}):
                title_emails = extract_emails_from_text(element["title"])
                emails.extend(title_emails)
                
            for element in soup.find_all("img", attrs={"alt": True}):
                alt_emails = extract_emails_from_text(element["alt"])
                emails.extend(alt_emails)
                
            for element in soup.find_all(attrs={"placeholder": True}):
                placeholder_emails = extract_emails_from_text(element["placeholder"])
                emails.extend(placeholder_emails)
            
            # Method 8: Extract and analyze HTML comments
            comments = soup.find_all(string=lambda text: isinstance(text, Comment))
            for comment in comments:
                comment_emails = extract_emails_from_text(comment)
                emails.extend(comment_emails)
            
            # Method 9: Extract content from <noscript> tags
            noscript_tags = soup.find_all('noscript')
            for noscript in noscript_tags:
                noscript_emails = extract_emails_from_text(noscript.get_text())
                emails.extend(noscript_emails)
                
                # Also check for obfuscated emails in noscript content
                if noscript.string:
                    noscript_obfuscated_emails = extract_obfuscated_emails_from_js(noscript.string)
                    emails.extend(noscript_obfuscated_emails)
            
            # Method 10: Check for non-standard attributes that might be used for obfuscation
            for element in soup.find_all():
                for attr, value in element.attrs.items():
                    # Skip already processed attributes
                    if attr in ['href', 'onclick', 'title', 'alt', 'placeholder'] or attr.startswith('data-'):
                        continue
                    
                    if isinstance(value, str) and ('@' in value or '(at)' in value or '[at]' in value):
                        attr_emails = extract_emails_from_text(value)
                        emails.extend(attr_emails)
        
        # Method 11: Execute JavaScript to find emails that might be generated dynamically
        try:
            # Get all text content from the page using JavaScript
            js_text = await self.page.evaluate('''
                () => {
                    return document.body.innerText;
                }
            ''')
            js_emails = extract_emails_from_text(js_text)
            emails.extend(js_emails)
            
            # Method 12: Extract all JavaScript from the page and analyze it
            js_content = await self.page.evaluate('''
                () => {
                    const scripts = Array.from(document.getElementsByTagName('script'));
                    return scripts.map(script => script.textContent || '').join('\\n');
                }
            ''')
            js_obfuscated_emails = extract_obfuscated_emails_from_js(js_content)
            emails.extend(js_obfuscated_emails)
            
            # Method 13: Extract emails from attributes using JavaScript
            attr_emails = await self.page.evaluate('''
                () => {
                    const emailRegex = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;
                    const attrEmails = [];
                    
                    // Check title, alt, placeholder attributes
                    const elementsWithAttrs = document.querySelectorAll('[title], [alt], [placeholder]');
                    for (const el of elementsWithAttrs) {
                        if (el.title) {
                            const matches = el.title.match(emailRegex);
                            if (matches) attrEmails.push(...matches);
                        }
                        if (el.alt) {
                            const matches = el.alt.match(emailRegex);
                            if (matches) attrEmails.push(...matches);
                        }
                        if (el.placeholder) {
                            const matches = el.placeholder.match(emailRegex);
                            if (matches) attrEmails.push(...matches);
                        }
                    }
                    
                    // Check all elements for any attribute that might contain an email
                    const allElements = document.querySelectorAll('*');
                    for (const el of allElements) {
                        for (const attr of el.attributes) {
                            if (['href', 'src', 'onclick', 'title', 'alt', 'placeholder'].includes(attr.name)) continue;
                            if (attr.value.includes('@') || attr.value.includes('(at)') || attr.value.includes('[at]')) {
                                const matches = attr.value.match(emailRegex);
                                if (matches) attrEmails.push(...matches);
                            }
                        }
                    }
                    
                    return attrEmails;
                }
            ''')
            emails.extend(attr_emails)
            
            # Method 14: Extract content from noscript tags using JavaScript
            noscript_emails = await self.page.evaluate('''
                () => {
                    const emailRegex = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;
                    const noscriptEmails = [];
                    
                    const noscriptTags = document.querySelectorAll('noscript');
                    for (const tag of noscriptTags) {
                        const matches = tag.textContent.match(emailRegex);
                        if (matches) noscriptEmails.push(...matches);
                    }
                    
                    return noscriptEmails;
                }
            ''')
            emails.extend(noscript_emails)
            
            # Method 15: Extract emails from HTML comments using JavaScript
            comment_emails = await self.page.evaluate('''
                () => {
                    const emailRegex = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;
                    const commentEmails = [];
                    
                    // Get all nodes in the document
                    const iterator = document.createNodeIterator(
                        document.documentElement,
                        NodeFilter.SHOW_COMMENT,
                        null,
                        false
                    );
                    
                    let node;
                    while (node = iterator.nextNode()) {
                        const matches = node.nodeValue.match(emailRegex);
                        if (matches) commentEmails.push(...matches);
                    }
                    
                    return commentEmails;
                }
            ''')
            emails.extend(comment_emails)
            
            # Method 26: Extract emails from CSS content properties using JavaScript
            css_emails = await self.page.evaluate('''
                () => {
                    const emailRegex = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;
                    const cssEmails = [];
                    
                    try {
                        // Get all stylesheets
                        const styleSheets = Array.from(document.styleSheets);
                        
                        for (const sheet of styleSheets) {
                            try {
                                // Skip cross-origin stylesheets
                                if (sheet.href && new URL(sheet.href).origin !== window.location.origin) {
                                    continue;
                                }
                                
                                // Get all CSS rules
                                const rules = Array.from(sheet.cssRules || []);
                                
                                for (const rule of rules) {
                                    // Check for content property in the rule
                                    if (rule.style && rule.style.content) {
                                        const content = rule.style.content;
                                        const matches = content.match(emailRegex);
                                        if (matches) cssEmails.push(...matches);
                                    }
                                }
                            } catch (e) {
                                // Skip stylesheets that can't be accessed due to CORS
                                continue;
                            }
                        }
                    } catch (e) {
                        // Ignore errors
                    }
                    
                    return cssEmails;
                }
            ''')
            emails.extend(css_emails)

            # Method 27: Extract emails from canvas elements
            canvas_emails = await self.page.evaluate('''
                () => {
                    const emailRegex = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;
                    const canvasEmails = [];
                    
                    try {
                        // Get all canvas elements
                        const canvasElements = document.querySelectorAll('canvas');
                        
                        for (const canvas of canvasElements) {
                            try {
                                // Try to get canvas data
                                const context = canvas.getContext('2d');
                                const dataURL = canvas.toDataURL();
                                
                                // Check if dataURL contains email-like patterns
                                const matches = dataURL.match(emailRegex);
                                if (matches) canvasEmails.push(...matches);
                            } catch (e) {
                                // Skip canvases that can't be accessed
                                continue;
                            }
                        }
                    } catch (e) {
                        // Ignore errors
                    }
                    
                    return canvasEmails;
                }
            ''')
            emails.extend(canvas_emails)

            # Method 28: Extract emails from shadow DOM
            shadow_dom_emails = await self.page.evaluate('''
                () => {
                    const emailRegex = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;
                    const shadowEmails = [];
                    
                    function extractFromShadowDOM(root) {
                        // Skip if not an element
                        if (!root || !root.querySelectorAll) return;
                        
                        // Get text content
                        const text = root.innerText || '';
                        const matches = text.match(emailRegex);
                        if (matches) shadowEmails.push(...matches);
                        
                        // Check all elements with shadow roots
                        const elementsWithShadow = root.querySelectorAll('*');
                        for (const el of elementsWithShadow) {
                            if (el.shadowRoot) {
                                extractFromShadowDOM(el.shadowRoot);
                            }
                        }
                    }
                    
                    try {
                        // Start with document body
                        const elementsWithShadow = document.querySelectorAll('*');
                        for (const el of elementsWithShadow) {
                            if (el.shadowRoot) {
                                extractFromShadowDOM(el.shadowRoot);
                            }
                        }
                    } catch (e) {
                        // Ignore errors
                    }
                    
                    return shadowEmails;
                }
            ''')
            emails.extend(shadow_dom_emails)

            # Method 29: Extract emails from dynamically loaded content by scrolling
            try:
                # Scroll to bottom to trigger lazy loading
                await self.page.evaluate('''
                    () => {
                        window.scrollTo(0, document.body.scrollHeight);
                    }
                ''')
                await self.page.wait_for_timeout(500)  # Wait for content to load
                
                # Get updated content
                updated_html = await self.page.content()
                updated_soup = BeautifulSoup(updated_html, 'lxml')
                
                # Extract emails from the updated content
                updated_text = updated_soup.get_text(" ", strip=True)
                updated_emails = extract_emails_from_text(updated_text)
                emails.extend(updated_emails)
            except Exception as e:
                logger.debug(f"Error extracting emails from scrolled content: {str(e)}")

            # Method 30: Extract emails from web storage (localStorage and sessionStorage)
            storage_emails = await self.page.evaluate('''
                () => {
                    const emailRegex = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;
                    const storageEmails = [];
                    
                    try {
                        // Check localStorage
                        for (let i = 0; i < localStorage.length; i++) {
                            const key = localStorage.key(i);
                            const value = localStorage.getItem(key);
                            
                            if (typeof value === 'string') {
                                const matches = value.match(emailRegex);
                                if (matches) storageEmails.push(...matches);
                            }
                        }
                        
                        // Check sessionStorage
                        for (let i = 0; i < sessionStorage.length; i++) {
                            const key = sessionStorage.key(i);
                            const value = sessionStorage.getItem(key);
                            
                            if (typeof value === 'string') {
                                const matches = value.match(emailRegex);
                                if (matches) storageEmails.push(...matches);
                            }
                        }
                    } catch (e) {
                        // Ignore storage access errors
                    }
                    
                    return storageEmails;
                }
            ''')
            emails.extend(storage_emails)
            
            # Method 31: Extract emails from <link> tags
            link_elements = soup.find_all('link')
            for link in link_elements:
                # Check rel attribute for author or me
                if link.has_attr('rel') and any(r in ['author', 'me'] for r in link['rel']):
                    if link.has_attr('href'):
                        href = link['href']
                        # Check for mailto: links
                        if href.startswith('mailto:'):
                            email = href[7:]  # Remove 'mailto:'
                            # Handle additional parameters in mailto links
                            if '?' in email:
                                email = email.split('?')[0]
                            if email and is_valid_email(email):
                                emails.append(email)
                        # Check for regular URLs that might contain emails
                        elif '@' in href:
                            link_emails = extract_emails_from_text(href)
                            emails.extend(link_emails)

            # Method 32: Extract emails from <address> elements
            address_elements = soup.find_all('address')
            for address in address_elements:
                # Get text content
                address_text = address.get_text(strip=True)
                address_emails = extract_emails_from_text(address_text)
                emails.extend(address_emails)
                
                # Also check for mailto: links within address elements
                for link in address.find_all('a', href=True):
                    href = link['href']
                    if href.startswith('mailto:'):
                        email = href[7:]  # Remove 'mailto:'
                        # Handle additional parameters in mailto links
                        if '?' in email:
                            email = email.split('?')[0]
                        if email and is_valid_email(email):
                            emails.append(email)

            # Method 33: Extract emails from <pre> and <code> elements
            code_elements = soup.find_all(['pre', 'code'])
            for element in code_elements:
                # Get text content
                code_text = element.get_text(strip=True)
                code_emails = extract_emails_from_text(code_text)
                emails.extend(code_emails)

            # Method 34: Extract emails from <style> tags (might contain emails in CSS comments)
            style_elements = soup.find_all('style')
            for style in style_elements:
                if style.string:
                    style_emails = extract_emails_from_text(style.string)
                    emails.extend(style_emails)

            # Method 35: Extract emails from <time> elements (sometimes used for contact timestamps)
            time_elements = soup.find_all('time')
            for time_el in time_elements:
                # Check datetime attribute
                if time_el.has_attr('datetime') and '@' in time_el['datetime']:
                    time_emails = extract_emails_from_text(time_el['datetime'])
                    emails.extend(time_emails)
                
                # Check text content
                time_text = time_el.get_text(strip=True)
                if '@' in time_text:
                    text_emails = extract_emails_from_text(time_text)
                    emails.extend(text_emails)

            # Method 36: Extract emails from <output> elements (might contain dynamically generated emails)
            output_elements = soup.find_all('output')
            for output in output_elements:
                output_text = output.get_text(strip=True)
                output_emails = extract_emails_from_text(output_text)
                emails.extend(output_emails)

            # Method 37: Extract emails from <details> and <summary> elements
            details_elements = soup.find_all(['details', 'summary'])
            for element in details_elements:
                details_text = element.get_text(strip=True)
                details_emails = extract_emails_from_text(details_text)
                emails.extend(details_emails)

            # Method 38: Extract emails from <blockquote> and <cite> elements
            quote_elements = soup.find_all(['blockquote', 'cite', 'q'])
            for element in quote_elements:
                quote_text = element.get_text(strip=True)
                quote_emails = extract_emails_from_text(quote_text)
                emails.extend(quote_emails)

            # Method 39: Extract emails from JavaScript-based animations
            animation_emails = await self.page.evaluate('''
                () => {
                    const emailRegex = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;
                    const animationEmails = [];
                    
                    try {
                        // Check for GSAP animations
                        if (window.gsap || window.TweenMax || window.TweenLite) {
                            const tweens = window.gsap ? window.gsap.getTweens() : 
                                        (window.TweenMax ? window.TweenMax.getAllTweens() : []);
                            
                            for (const tween of tweens) {
                                if (tween.target && tween.target.textContent) {
                                    const matches = tween.target.textContent.match(emailRegex);
                                    if (matches) animationEmails.push(...matches);
                                }
                            }
                        }
                        
                        // Check for CSS animations
                        const animatedElements = document.querySelectorAll('*[class*="animate"], *[class*="anim"]');
                        for (const el of animatedElements) {
                            if (el.textContent) {
                                const matches = el.textContent.match(emailRegex);
                                if (matches) animationEmails.push(...matches);
                            }
                        }
                    } catch (e) {
                        // Ignore errors
                    }
                    
                    return animationEmails;
                }
            ''')
            emails.extend(animation_emails)

            # Method 40: Extract emails from Web Components' Shadow DOM using JavaScript
            web_component_emails = await self.page.evaluate('''
                () => {
                    const emailRegex = /[a-zA-Z0-9._%+\\-]+@[a-zA-Z0-9.\\-]+\\.[a-zA-Z]{2,}/g;
                    const wcEmails = [];
                    
                    try {
                        // Find all custom elements (those with a dash in the name)
                        const customElements = Array.from(document.querySelectorAll('*')).filter(el => 
                            el.tagName.includes('-') && el.tagName !== 'META-INF'
                        );
                        
                        for (const el of customElements) {
                            // Check text content
                            if (el.textContent) {
                                const matches = el.textContent.match(emailRegex);
                                if (matches) wcEmails.push(...matches);
                            }
                            
                            // Check shadow DOM if available
                            if (el.shadowRoot) {
                                const shadowText = el.shadowRoot.textContent || '';
                                const shadowMatches = shadowText.match(emailRegex);
                                if (shadowMatches) wcEmails.push(...shadowMatches);
                            }
                        }
                    } catch (e) {
                        // Ignore errors
                    }
                    
                    return wcEmails;
                }
            ''')
            emails.extend(web_component_emails)
            
            # Method 41: Extract emails from data-enc-email attributes
            data_enc_emails = await self._extract_emails_from_data_enc_email(soup)
            emails.extend(data_enc_emails)
            
            # Method 16: Look for elements with onclick handlers that might reveal emails
            # Limit the number of elements to check to avoid long processing
            email_elements = await self.page.query_selector_all('[onclick*="mail"], [onclick*="email"]')
            for i, element in enumerate(email_elements):
                if i >= 5:  # Limit to 5 elements to avoid long processing
                    break
                try:
                    await element.click()
                    await self.page.wait_for_timeout(300)  # Reduced wait time
                    
                    # Get updated page content
                    updated_html = await self.page.content()
                    updated_soup = BeautifulSoup(updated_html, 'lxml')
                    
                    # Extract emails from the updated content
                    updated_text = updated_soup.get_text(" ", strip=True)
                    updated_emails = extract_emails_from_text(updated_text)
                    emails.extend(updated_emails)
                    
                    # Also check for newly revealed JavaScript
                    updated_scripts = updated_soup.find_all('script')
                    for script in updated_scripts:
                        if script.string:
                            updated_js_emails = extract_obfuscated_emails_from_js(script.string)
                            emails.extend(updated_js_emails)
                except:
                    continue
        except Exception as e:
            logger.warning(f"Error executing JavaScript for email extraction: {str(e)}")
        
        # Remove duplicates while preserving order
        unique_emails = []
        seen = set()
        for email in emails:
            if email not in seen:
                seen.add(email)
                unique_emails.append(email)
        
        logger.info(f"Extracted {len(unique_emails)} emails from {url} using Playwright")
        return unique_emails
    
    async def _extract_emails_from_data_enc_email(self, soup):
        """
        Extract emails from data-enc-email attributes.
        
        Args:
            soup (BeautifulSoup): The parsed HTML
            
        Returns:
            list: List of extracted email addresses
        """
        if not soup:
            return []
        
        emails = []
        
        # Find all elements with data-enc-email attribute
        elements_with_data_enc_email = soup.find_all(attrs={"data-enc-email": True})
        for element in elements_with_data_enc_email:
            encoded_email = element.get('data-enc-email')
            if encoded_email:
                from utils import decode_data_enc_email
                decoded_email = decode_data_enc_email(encoded_email)
                if decoded_email:
                    emails.append(decoded_email)
                    logger.info(f"Decoded email from data-enc-email attribute: {decoded_email}")
        
        # Also try to extract using JavaScript
        try:
            js_data_enc_emails = await self.page.evaluate('''
                () => {
                    const dataEncEmails = [];
                    const elements = document.querySelectorAll('[data-enc-email]');
                    for (const el of elements) {
                        dataEncEmails.push(el.getAttribute('data-enc-email'));
                    }
                    return dataEncEmails;
                }
            ''')
            
            for encoded_email in js_data_enc_emails:
                if encoded_email:
                    from email_extractor.utils import decode_data_enc_email
                    decoded_email = decode_data_enc_email(encoded_email)
                    if decoded_email:
                        emails.append(decoded_email)
                        logger.info(f"Decoded email from data-enc-email attribute using JavaScript: {decoded_email}")
        except Exception as e:
            logger.debug(f"Error extracting data-enc-email attributes using JavaScript: {str(e)}")
        
        return emails
    
    async def find_contact_pages(self, base_url):
        """
        Find potential contact pages from the current page with timeout protection.
        
        Args:
            base_url (str): The base URL
            
        Returns:
            list: List of contact page URLs sorted by relevance
        """
        try:
            # Create a task with timeout
            contact_task = asyncio.create_task(self._find_contact_pages_impl(base_url))
            try:
                return await asyncio.wait_for(contact_task, timeout=CONTACT_PAGE_SEARCH_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning(f"Contact page search timed out for {base_url}")
                return []
        except Exception as e:
            logger.error(f"Error in find_contact_pages: {str(e)}")
            return []
    
    async def _find_contact_pages_impl(self, base_url):
        """Implementation of contact page finding with proper error handling."""
        try:
            # Get all links from the page
            links = await self.page.query_selector_all('a[href]')
            
            contact_links = []
            for link in links:
                try:
                    href = await link.get_attribute('href')
                    link_text = await link.text_content()
                    
                    # Skip empty, javascript, and anchor links
                    if not href or href.startswith(('javascript:', '#', 'tel:', 'mailto:')):
                        continue
                    
                    # Normalize the URL
                    full_url = normalize_url(href, base_url)
                    if not full_url:
                        continue
                    
                    # Calculate contact page likelihood score
                    score = is_likely_contact_page(full_url, link_text)
                    if score > 0:
                        contact_links.append((full_url, score))
                except:
                    continue
            
            # Sort by score (highest first) and remove duplicates
            contact_links.sort(key=lambda x: x[1], reverse=True)
            
            # Extract just the URLs, preserving order but removing duplicates
            unique_urls = []
            seen = set()
            for url, _ in contact_links:
                if url not in seen:
                    seen.add(url)
                    unique_urls.append(url)
            
            logger.info(f"Found {len(unique_urls)} potential contact pages using Playwright")
            return unique_urls
            
        except Exception as e:
            logger.error(f"Error finding contact pages with Playwright: {str(e)}")
            return []
    
    async def cleanup(self):
        """Clean up Playwright resources."""
        try:
            if self.page:
                await self.page.close()
                self.page = None
            
            if self.context:
                await self.context.close()
                self.context = None
            
            if self.browser:
                await self.browser.close()
                self.browser = None
            
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
            
            logger.info("Playwright resources cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up Playwright resources: {str(e)}")