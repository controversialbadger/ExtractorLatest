"""
HTTP request handler for the Email Extractor.
"""

import requests
from bs4 import BeautifulSoup, Comment
import logging
import time
from tenacity import retry, stop_after_attempt, wait_exponential
from urllib.parse import urljoin

from email_extractor.config import HTTP_TIMEOUT, MAX_RETRIES, RETRY_BACKOFF_FACTOR
from email_extractor.utils import (
    get_random_user_agent, extract_emails_from_text, 
    normalize_url, is_likely_contact_page, decode_email_entities,
    extract_obfuscated_emails_from_js, is_valid_email,
    logger
)

class HTTPHandler:
    """Handles HTTP requests and email extraction from HTML content."""
    
    def __init__(self):
        """Initialize the HTTP handler with a session."""
        self.session = requests.Session()
        self.visited_urls = set()
    
    def _get_headers(self):
        """Get request headers with a random user agent."""
        return {
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
        }
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=RETRY_BACKOFF_FACTOR, min=1, max=10),
        reraise=True
    )
    def fetch_url(self, url):
        """
        Fetch a URL with retry logic.
        
        Args:
            url (str): The URL to fetch
            
        Returns:
            tuple: (response_text, soup) or (None, None) if failed
        """
        if url in self.visited_urls:
            logger.debug(f"Skipping already visited URL: {url}")
            return None, None
        
        self.visited_urls.add(url)
        
        try:
            logger.info(f"Fetching URL: {url}")
            response = self.session.get(
                url,
                headers=self._get_headers(),
                timeout=HTTP_TIMEOUT,
                allow_redirects=True
            )
            
            # Check if the request was successful
            if response.status_code != 200:
                logger.warning(f"Failed to fetch {url}, status code: {response.status_code}")
                return None, None
            
            # Check content type
            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type:
                logger.warning(f"Skipping non-HTML content: {content_type} for {url}")
                return None, None
            
            # Parse the HTML
            soup = BeautifulSoup(response.text, 'lxml')
            return response.text, soup
            
        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            raise  # Let retry handle this
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {str(e)}")
            return None, None
    
    def extract_emails_from_page(self, url):
        """
        Extract emails from a web page.
        
        Args:
            url (str): The URL to extract emails from
            
        Returns:
            list: List of extracted email addresses
        """
        html_text, soup = self.fetch_url(url)
        if not html_text or not soup:
            return []
        
        emails = []
        
        # Method 1: Extract from raw HTML (catches obfuscated emails)
        decoded_html = decode_email_entities(html_text)
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
            
            # Method 11: Extract emails from meta tags
            meta_tags = soup.find_all('meta')
            for meta in meta_tags:
                # Check content attribute
                if meta.has_attr('content') and '@' in meta['content']:
                    meta_emails = extract_emails_from_text(meta['content'])
                    emails.extend(meta_emails)

            # Method 12: Extract emails from structured data (JSON-LD)
            json_ld_tags = soup.find_all('script', {'type': 'application/ld+json'})
            for tag in json_ld_tags:
                if tag.string:
                    try:
                        # Extract emails from the JSON-LD content
                        json_ld_emails = extract_emails_from_text(tag.string)
                        emails.extend(json_ld_emails)
                    except Exception as e:
                        logger.debug(f"Error parsing JSON-LD: {str(e)}")

            # Method 13: Extract emails from form elements
            form_elements = soup.find_all(['input', 'textarea'])
            for element in form_elements:
                # Check various attributes that might contain email hints
                for attr in ['value', 'placeholder', 'name', 'id', 'aria-label']:
                    if element.has_attr(attr) and '@' in element[attr]:
                        form_emails = extract_emails_from_text(element[attr])
                        emails.extend(form_emails)
                
                # Special case for email input fields
                if element.name == 'input' and element.get('type') == 'email' and element.has_attr('value'):
                    if is_valid_email(element['value']):
                        emails.append(element['value'])

            # Method 14: Extract emails from accessibility attributes
            elements_with_aria = soup.find_all(lambda tag: any(attr.startswith('aria-') for attr in tag.attrs))
            for element in elements_with_aria:
                for attr, value in element.attrs.items():
                    if attr.startswith('aria-') and isinstance(value, str) and '@' in value:
                        aria_emails = extract_emails_from_text(value)
                        emails.extend(aria_emails)

            # Method 15: Extract emails from SVG elements and their attributes
            svg_elements = soup.find_all('svg')
            for svg in svg_elements:
                # Get text content from SVG
                svg_text = svg.get_text(strip=True)
                svg_text_emails = extract_emails_from_text(svg_text)
                emails.extend(svg_text_emails)
                
                # Check SVG element attributes
                for element in svg.find_all():
                    for attr, value in element.attrs.items():
                        if isinstance(value, str) and '@' in value:
                            svg_attr_emails = extract_emails_from_text(value)
                            emails.extend(svg_attr_emails)

            # Method 16: Extract emails from custom elements and web components
            custom_elements = soup.find_all(lambda tag: '-' in tag.name)
            for element in custom_elements:
                # Get text content
                custom_text = element.get_text(strip=True)
                custom_text_emails = extract_emails_from_text(custom_text)
                emails.extend(custom_text_emails)
                
                # Check attributes
                for attr, value in element.attrs.items():
                    if isinstance(value, str) and '@' in value:
                        custom_attr_emails = extract_emails_from_text(value)
                        emails.extend(custom_attr_emails)

            # Method 17: Extract emails from microdata attributes
            elements_with_microdata = soup.find_all(lambda tag: any(attr.startswith('itemp') for attr in tag.attrs))
            for element in elements_with_microdata:
                for attr, value in element.attrs.items():
                    if attr in ['itemprop', 'itemtype'] and isinstance(value, str) and '@' in value:
                        microdata_emails = extract_emails_from_text(value)
                        emails.extend(microdata_emails)

            # Method 18: Extract emails from source code comments (HTML)
            # This is already covered by Method 8, but we'll add a more specific check for email patterns
            for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                if '@' in comment or '(at)' in comment or '[at]' in comment:
                    comment_emails = extract_emails_from_text(comment)
                    emails.extend(comment_emails)

            # Method 19: Extract emails from iframe src attributes (sometimes used for contact forms)
            iframe_elements = soup.find_all('iframe')
            for iframe in iframe_elements:
                if iframe.has_attr('src'):
                    src = iframe['src']
                    # Check for data: URIs that might contain emails
                    if src.startswith('data:') and '@' in src:
                        iframe_emails = extract_emails_from_text(src)
                        emails.extend(iframe_emails)

            # Method 20: Extract emails from schema.org markup
            schema_elements = soup.find_all(attrs={"itemtype": True})
            for element in schema_elements:
                itemtype = element['itemtype']
                if 'schema.org/Person' in itemtype or 'schema.org/Organization' in itemtype:
                    # Find email properties
                    email_props = element.find_all(attrs={"itemprop": "email"})
                    for prop in email_props:
                        if prop.has_attr('content'):
                            if is_valid_email(prop['content']):
                                emails.append(prop['content'])
                        else:
                            prop_text = prop.get_text(strip=True)
                            if is_valid_email(prop_text):
                                emails.append(prop_text)

            # Method 21: Extract emails from <link> tags
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

            # Method 22: Extract emails from <address> elements
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

            # Method 23: Extract emails from <pre> and <code> elements
            code_elements = soup.find_all(['pre', 'code'])
            for element in code_elements:
                # Get text content
                code_text = element.get_text(strip=True)
                code_emails = extract_emails_from_text(code_text)
                emails.extend(code_emails)

            # Method 24: Extract emails from <style> tags (might contain emails in CSS comments)
            style_elements = soup.find_all('style')
            for style in style_elements:
                if style.string:
                    style_emails = extract_emails_from_text(style.string)
                    emails.extend(style_emails)

            # Method 25: Extract emails from <time> elements (sometimes used for contact timestamps)
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

            # Method 26: Extract emails from <output> elements (might contain dynamically generated emails)
            output_elements = soup.find_all('output')
            for output in output_elements:
                output_text = output.get_text(strip=True)
                output_emails = extract_emails_from_text(output_text)
                emails.extend(output_emails)

            # Method 27: Extract emails from <details> and <summary> elements
            details_elements = soup.find_all(['details', 'summary'])
            for element in details_elements:
                details_text = element.get_text(strip=True)
                details_emails = extract_emails_from_text(details_text)
                emails.extend(details_emails)

            # Method 29: Extract emails from <blockquote> and <cite> elements
            quote_elements = soup.find_all(['blockquote', 'cite', 'q'])
            for element in quote_elements:
                quote_text = element.get_text(strip=True)
                quote_emails = extract_emails_from_text(quote_text)
                emails.extend(quote_emails)
            
            # Method 30: Extract emails from data-enc-email attributes
            data_enc_emails = self._extract_emails_from_data_enc_email(soup)
            emails.extend(data_enc_emails)
        
        # Remove duplicates while preserving order
        unique_emails = []
        seen = set()
        for email in emails:
            if email not in seen:
                seen.add(email)
                unique_emails.append(email)
        
        logger.info(f"Extracted {len(unique_emails)} emails from {url}")
        return unique_emails
    
    def _extract_emails_from_data_enc_email(self, soup):
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
                from email_extractor.utils import decode_data_enc_email
                decoded_email = decode_data_enc_email(encoded_email)
                if decoded_email:
                    emails.append(decoded_email)
                    logger.info(f"Decoded email from data-enc-email attribute: {decoded_email}")
        
        return emails
    
    def find_contact_pages(self, base_url, soup):
        """
        Find potential contact pages from the given soup.
        
        Args:
            base_url (str): The base URL
            soup (BeautifulSoup): The parsed HTML
            
        Returns:
            list: List of contact page URLs sorted by relevance
        """
        if not soup:
            return []
        
        contact_links = []
        
        # Find all links
        for link in soup.find_all('a', href=True):
            href = link['href']
            link_text = link.get_text(strip=True)
            
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
        
        # Sort by score (highest first) and remove duplicates
        contact_links.sort(key=lambda x: x[1], reverse=True)
        
        # Extract just the URLs, preserving order but removing duplicates
        unique_urls = []
        seen = set()
        for url, _ in contact_links:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        logger.info(f"Found {len(unique_urls)} potential contact pages")
        return unique_urls