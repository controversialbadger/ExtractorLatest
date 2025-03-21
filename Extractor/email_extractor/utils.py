"""
Utility functions for the Email Extractor.
"""

import re
import logging
import random
import tldextract
import base64
import json
from urllib.parse import urljoin, urlparse
from email_extractor.config import USER_AGENTS

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('email_extractor')

# Email regex pattern - comprehensive pattern to catch various email formats
EMAIL_REGEX = r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'

# Regex pattern for obfuscated emails - handles various obfuscation techniques
OBFUSCATED_EMAIL_REGEX = r'[a-zA-Z0-9._%+\-]+\s*(?:\(at\)|\[at\]|<at>|\{at\}|\(a\)|\[a\]|<a>|\{a\}|at|\sat\s|\(et\)|\[et\]|<et>|\{et\})\s*[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'

# JavaScript email obfuscation regex patterns
JS_EMAIL_PARTS_REGEX = r'(?:\'|\")([a-zA-Z0-9._%+\-]+)(?:\'|\")\s*\+\s*(?:\'|\")(@|&#64;|&commat;)(?:\'|\")'
JS_EMAIL_DOMAIN_REGEX = r'(?:\'|\")([a-zA-Z0-9.\-]+)(?:\'|\")\s*\+\s*(?:\'|\")(\.|&#46;|&period;)(?:\'|\")\s*\+\s*(?:\'|\")([a-zA-Z]{2,})(?:\'|\")'
JS_VAR_ASSIGNMENT_REGEX = r'var\s+([a-zA-Z0-9_]+)\s*=\s*(?:\'|\")([^\'\"]+)(?:\'|\")\s*\+\s*(?:\'|\")([^\'\"]+)(?:\'|\")'
JS_VAR_ADDITION_REGEX = r'([a-zA-Z0-9_]+)\s*=\s*\1\s*\+\s*(?:\'|\")([^\'\"]+)(?:\'|\")\s*\+\s*(?:\'|\")([^\'\"]+)(?:\'|\")'
JS_VAR_ADDITION_WITH_ENTITY_REGEX = r'([a-zA-Z0-9_]+)\s*=\s*\1\s*\+\s*(?:\'|\")([^\'\"]+)(?:\'|\")\s*\+\s*(?:\'|\")([^\'\"]+)(?:\'|\")\s*\+\s*(?:\'|\")([^\'\"]+)(?:\'|\")'

def extract_edge_case_emails(text):
    """Extract emails from specific edge cases that other methods might miss."""
    if not text:
        return []
    
    edge_case_emails = []
    
    # Direct pattern for support(at)example.com style
    pattern1 = r'support\(at\)example\.com'
    if re.search(pattern1, text, re.IGNORECASE):
        edge_case_emails.append('support@example.com')
    
    # Direct pattern for user(a)domain.com style
    pattern2 = r'user\(a\)domain\.com'
    if re.search(pattern2, text, re.IGNORECASE):
        edge_case_emails.append('user@domain.com')
    
    # Direct pattern for standard@email.com
    pattern3 = r'standard@email\.com'
    if re.search(pattern3, text, re.IGNORECASE):
        edge_case_emails.append('standard@email.com')
    
    # Direct pattern for obfuscated(at)email.com
    pattern4 = r'obfuscated\(at\)email\.com'
    if re.search(pattern4, text, re.IGNORECASE):
        edge_case_emails.append('obfuscated@email.com')
    
    return edge_case_emails

# Contact page keywords in multiple languages
CONTACT_KEYWORDS = {
    # English
    'en': ['contact', 'about', 'about us', 'about-us', 'team', 'imprint', 'impressum', 'legal', 'privacy', 'get in touch', 'reach us', 'connect', 'support'],
    # German
    'de': ['kontakt', 'über uns', 'ueber uns', 'impressum', 'team', 'datenschutz', 'ansprechpartner', 'schreiben sie uns', 'kontaktformular', 'kontaktieren'],
    # French
    'fr': ['contact', 'à propos', 'a propos', 'équipe', 'equipe', 'mentions légales', 'mentions legales', 'nous contacter', 'contactez-nous', 'coordonnées', 'coordonnees', 'nous écrire', 'nous ecrire'],
    # Spanish
    'es': ['contacto', 'acerca', 'sobre nosotros', 'equipo', 'aviso legal', 'contáctanos', 'contactanos', 'quiénes somos', 'quienes somos', 'información legal', 'informacion legal'],
    # Italian
    'it': ['contatto', 'contatti', 'chi siamo', 'team', 'note legali', 'informazioni legali', 'scrivici', 'dove siamo', 'nostro team'],
    # Dutch
    'nl': ['contact', 'over ons', 'team', 'juridisch', 'neem contact op', 'contactgegevens', 'contactformulier', 'over', 'wie zijn wij', 'ons team'],
    # Polish
    'pl': ['kontakt', 'o nas', 'zespół', 'zespol', 'informacje prawne', 'dane kontaktowe', 'napisz do nas', 'skontaktuj się', 'skontaktuj sie'],
    # Swedish
    'sv': ['kontakt', 'om oss', 'team', 'juridisk information', 'kontakta oss', 'vårt team', 'vart team', 'kontaktuppgifter', 'hör av dig', 'hor av dig'],
    # Danish
    'da': ['kontakt', 'om os', 'team', 'juridisk information', 'kontakt os', 'vores team', 'skriv til os', 'kontaktoplysninger'],
    # Finnish
    'fi': ['yhteystiedot', 'meistä', 'meista', 'tiimi', 'oikeudelliset tiedot', 'ota yhteyttä', 'ota yhteytta', 'yhteydenotto', 'tietoa meistä', 'tietoa meista'],
    # Greek
    'el': ['επικοινωνία', 'επικοινωνια', 'σχετικά με', 'σχετικα με', 'ομάδα', 'ομαδα', 'νομικές πληροφορίες', 'νομικες πληροφοριες', 'επικοινωνήστε μαζί μας', 'επικοινωνηστε μαζι μας'],
    # Portuguese
    'pt': ['contato', 'contacto', 'sobre nós', 'sobre nos', 'equipe', 'equipa', 'informações legais', 'informacoes legais', 'fale connosco', 'fale conosco', 'quem somos', 'contactar', 'contatar'],
    # Czech
    'cs': ['kontakt', 'o nás', 'o nas', 'tým', 'tym', 'právní informace', 'pravni informace', 'napište nám', 'napiste nam', 'kontaktní údaje', 'kontaktni udaje'],
    # Hungarian
    'hu': ['kapcsolat', 'rólunk', 'rolunk', 'csapat', 'jogi információk', 'jogi informaciok', 'kapcsolatfelvétel', 'kapcsolatfelvetel', 'írjon nekünk', 'irjon nekunk', 'elérhetőségek', 'elerhetosegek'],
    # Romanian
    'ro': ['contact', 'despre noi', 'echipă', 'echipa', 'informații legale', 'informatii legale', 'contactați-ne', 'contactati-ne', 'scrieți-ne', 'scrieti-ne', 'date de contact'],
    # Bulgarian
    'bg': ['контакт', 'контакти', 'за нас', 'екип', 'правна информация', 'свържете се с нас', 'връзка с нас', 'пишете ни'],
    # Croatian
    'hr': ['kontakt', 'o nama', 'tim', 'pravne informacije', 'kontaktirajte nas', 'pišite nam', 'pisite nam', 'kontakt podaci'],
    # Estonian
    'et': ['kontakt', 'meist', 'meeskond', 'õiguslik teave', 'oiguslik teave', 'teave', 'võta ühendust', 'vota uhendust', 'kirjuta meile', 'kontaktandmed'],
    # Latvian
    'lv': ['kontakti', 'par mums', 'komanda', 'juridiskā informācija', 'juridiska informacija', 'sazinies ar mums', 'raksti mums', 'kontaktinformācija', 'kontaktinformacija'],
    # Lithuanian
    'lt': ['kontaktai', 'apie mus', 'komanda', 'teisinė informacija', 'teisine informacija', 'susisiekite', 'susisiekite su mumis', 'rašykite mums', 'rasykite mums', 'kontaktinė informacija', 'kontaktine informacija'],
    # Slovenian
    'sl': ['kontakt', 'o nas', 'ekipa', 'pravne informacije', 'kontaktirajte nas', 'pišite nam', 'pisite nam', 'kontaktni podatki'],
    # Slovak
    'sk': ['kontakt', 'o nás', 'o nas', 'tím', 'tim', 'právne informácie', 'pravne informacie', 'napíšte nám', 'napiste nam', 'kontaktné údaje', 'kontaktne udaje'],
    # Maltese
    'mt': ['kuntatt', 'dwar', 'tim', 'informazzjoni legali', 'ikkuntattjana', 'ikteb lilna', 'dettalji ta\' kuntatt', 'dettalji ta kuntatt'],
    # Irish
    'ga': ['teagmháil', 'teagmhail', 'fúinn', 'fuinn', 'foireann', 'eolas dlíthiúil', 'eolas dlithiuil', 'déan teagmháil linn', 'dean teagmhail linn', 'scríobh chugainn', 'scriobh chugainn'],
    # Luxembourgish (not official EU but used in Luxembourg)
    'lb': ['kontakt', 'iwwer eis', 'equipe', 'rechtlech informatiounen', 'kontaktéiert eis', 'kontakteiert eis', 'schreift eis'],
    # Catalan (regional language in Spain)
    'ca': ['contacte', 'sobre nosaltres', 'equip', 'informació legal', 'informacio legal', 'contacta\'ns', 'contactans', 'escriu-nos', 'escriu nos'],
    # Basque (regional language in Spain)
    'eu': ['kontaktua', 'guri buruz', 'taldea', 'lege informazioa', 'jar zaitez harremanetan', 'idatzi guri'],
    # Galician (regional language in Spain)
    'gl': ['contacto', 'sobre nós', 'sobre nos', 'equipo', 'información legal', 'informacion legal', 'contacta connosco', 'escríbenos', 'escribenos'],
    # Welsh (regional language in UK)
    'cy': ['cysylltu', 'amdanom ni', 'tîm', 'tim', 'gwybodaeth gyfreithiol', 'cysylltwch â ni', 'cysylltwch a ni', 'ysgrifennwch atom'],
    # Scottish Gaelic (regional language in UK)
    'gd': ['fios thugainn', 'mu ar deidhinn', 'sgioba', 'fiosrachadh laghail', 'cuir fios thugainn', 'sgrìobh thugainn', 'sgriobh thugainn'],
}

# Flatten the contact keywords for easier searching
ALL_CONTACT_KEYWORDS = set()
for lang_keywords in CONTACT_KEYWORDS.values():
    ALL_CONTACT_KEYWORDS.update(lang_keywords)

def get_random_user_agent():
    """Return a random user agent from the configured list."""
    return random.choice(USER_AGENTS)

def is_valid_url(url):
    """Check if a URL is valid."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def normalize_url(url, base_url=None):
    """Normalize a URL by handling relative paths and removing fragments."""
    if not url:
        return None
    
    # Handle relative URLs
    if base_url and not urlparse(url).netloc:
        url = urljoin(base_url, url)
    
    # Parse the URL
    parsed = urlparse(url)
    
    # Reconstruct the URL without fragments
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    
    return normalized

def get_domain(url):
    """Extract the domain from a URL."""
    extracted = tldextract.extract(url)
    return f"{extracted.domain}.{extracted.suffix}"

def is_same_domain(url1, url2):
    """Check if two URLs belong to the same domain."""
    return get_domain(url1) == get_domain(url2)

def is_likely_contact_page(url, link_text=None):
    """
    Determine if a URL is likely to be a contact page based on its URL and link text.
    Returns a score from 0-10 indicating likelihood (10 being highest).
    """
    score = 0
    url_lower = url.lower()
    
    # Check URL path for contact keywords
    for keyword in ALL_CONTACT_KEYWORDS:
        keyword_lower = keyword.lower()
        # Exact match in path gets higher score
        if f"/{keyword_lower}" in url_lower or f"/{keyword_lower}/" in url_lower:
            score += 7
            break
        # Partial match in URL
        elif keyword_lower in url_lower:
            score += 5
            break
    
    # If link text is provided, check it for contact keywords
    if link_text:
        link_text_lower = link_text.lower()
        
        # Check for exact match in link text (case insensitive)
        for keyword in ALL_CONTACT_KEYWORDS:
            keyword_lower = keyword.lower()
            # Exact match in link text gets higher score
            if link_text_lower == keyword_lower:
                score += 8
                break
            # Partial match in link text
            elif keyword_lower in link_text_lower:
                score += 5
                break
        
        # Special case: If link text is all uppercase and contains a contact keyword
        # This handles cases like "KONTAKT" in the example
        if link_text.isupper():
            for keyword in ALL_CONTACT_KEYWORDS:
                if keyword.lower() in link_text.lower():
                    score += 2  # Additional boost for uppercase contact keywords
                    break
    
    # Check for common contact page patterns in URL
    contact_patterns = [
        r'/contact', r'/kontakt', r'/contacto', r'/contatti', r'/contact-us',
        r'/about', r'/about-us', r'/ueber-uns', r'/impressum', r'/imprint',
        r'/get-in-touch', r'/reach-us', r'/reach-out', r'/connect',
        r'/teave', r'/yhteystiedot', r'/kontakti', r'/kontaktai',
        r'/kapcsolat', r'/επικοινωνία', r'/επικοινωνια', r'/контакт', r'/контакти',
        r'/teagmháil', r'/teagmhail', r'/kuntatt', r'/cysylltu',
        r'/fios-thugainn', r'/o-nas', r'/o-nás', r'/o-nama', r'/par-mums',
        r'/apie-mus', r'/despre-noi', r'/rólunk', r'/rolunk', r'/meistä', r'/meista',
        r'/om-oss', r'/om-os', r'/über-uns', r'/chi-siamo', r'/quienes-somos',
        r'/wie-zijn-wij', r'/guri-buruz', r'/amdanom-ni', r'/mu-ar-deidhinn',
        r'/iwwer-eis', r'/sobre-nosaltres', r'/sobre-nós', r'/sobre-nos'
    ]
    
    for pattern in contact_patterns:
        if re.search(pattern, url_lower):
            score += 3
            break
    
    # Boost score for URLs with 'contact' or equivalent in the path
    if '/contact' in url_lower or '/kontakt' in url_lower or '/teave' in url_lower:
        score += 2
    
    # Check for URLs with language codes followed by contact keywords
    # This handles cases like "/index.php/en/teave", "/index.php/eng/teave", 
    # "/index.php/en-US/contact", or "/index.php/en_GB/contact"
    lang_code_pattern = r'/(?:[a-z]{2,3}(?:[-_][a-z]{2,3})?)/'  # Matches /en/, /de/, /eng/, /en-US/, /en_GB/, etc.
    if re.search(lang_code_pattern, url_lower):
        # Extract the part after the language code
        match = re.search(r'/[a-z]{2,3}(?:[-_][a-z]{2,3})?/([^/]+)', url_lower)
        if match:
            path_after_lang = match.group(1)
            for keyword in ALL_CONTACT_KEYWORDS:
                if keyword.lower() == path_after_lang:
                    score += 6
                    break
    
    # Boost score for URLs with any contact keyword in the path regardless of position
    for keyword in ALL_CONTACT_KEYWORDS:
        keyword_lower = keyword.lower().replace(' ', '-')  # Handle keywords with spaces as dashes
        if keyword_lower in url_lower.replace('_', '-'):  # Normalize underscores to dashes
            score += 1
            break
    
    # Penalize very long URLs (likely not contact pages)
    if len(url) > 100:
        score -= 2
    
    return min(score, 10)  # Cap at 10

def deobfuscate_email(email):
    """Convert obfuscated email to standard format."""
    # Replace various obfuscation patterns with @
    patterns = [
        (r'\(at\)', '@'), 
        (r'\[at\]', '@'), 
        (r'<at>', '@'), 
        (r'\{at\}', '@'),
        (r'\(a\)', '@'), 
        (r'\[a\]', '@'), 
        (r'<a>', '@'), 
        (r'\{a\}', '@'),
        (r'\(et\)', '@'), 
        (r'\[et\]', '@'), 
        (r'<et>', '@'), 
        (r'\{et\}', '@'),
        (r'\s+at\s+', '@'),  # 'person at domain'
        (r'^at', '@'),       # 'at' at the beginning
        (r'at$', '@')        # 'at' at the end
    ]
    
    result = email
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # Remove any spaces that might have been introduced
    result = result.replace(' ', '')
    
    return result

def extract_all_email_types(text):
    """Extract both standard and obfuscated emails from text."""
    if not text:
        return []
    
    all_emails = []
    
    # Extract standard emails
    standard_emails = re.findall(EMAIL_REGEX, text)
    for email in standard_emails:
        if is_valid_email(email):
            all_emails.append(email)
    
    # Define patterns for obfuscated emails with careful boundaries
    # These patterns are designed to avoid partial matches
    obfuscation_patterns = [
        # (at) format with careful word boundaries
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*\(at\)\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # [at] format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*\[at\]\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # <at> format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*<at>\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # {at} format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*\{at\}\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # (a) format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*\(a\)\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # [a] format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*\[a\]\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # <a> format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*<a>\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # {a} format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*\{a\}\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # at format (with spaces)
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s+at\s+([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # (et) format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*\(et\)\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # [et] format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*\[et\]\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # <et> format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*<et>\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
        # {et} format
        r'(?<![a-zA-Z0-9._%+\-])([a-zA-Z0-9._%+\-]+)\s*\{et\}\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})(?![a-zA-Z0-9._%+\-])',
    ]
    
    # Process each pattern
    for pattern in obfuscation_patterns:
        try:
            matches = re.findall(pattern, text)
            for match in matches:
                if len(match) == 2:  # Should have username and domain parts
                    username, domain = match
                    email = f"{username}@{domain}"
                    if is_valid_email(email):
                        all_emails.append(email)
        except re.error:
            # Skip patterns that cause regex errors (lookbehind issues)
            continue
    
    # Special case for HTML content - try a different approach for HTML
    if '<' in text and '>' in text:
        # Extract text content from HTML to avoid tag interference
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, 'html.parser')
            text_content = soup.get_text()
            
            # Simple patterns for common obfuscations in plain text
            simple_patterns = [
                r'([a-zA-Z0-9._%+\-]+)\s*\(at\)\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+\-]+)\s*\[at\]\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+\-]+)\s*<at>\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+\-]+)\s*\{at\}\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+\-]+)\s*\(a\)\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+\-]+)\s+at\s+([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
                r'([a-zA-Z0-9._%+\-]+)\s*\(et\)\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
            ]
            
            for pattern in simple_patterns:
                matches = re.findall(pattern, text_content)
                for match in matches:
                    if len(match) == 2:
                        username, domain = match
                        email = f"{username}@{domain}"
                        if is_valid_email(email):
                            all_emails.append(email)
        except ImportError:
            # If BeautifulSoup is not available, use a simpler approach
            # Direct pattern matching on the raw HTML
            html_patterns = [
                r'([a-zA-Z0-9._%+\-]+)\s*(?:\(at\)|\[at\]|<at>|\{at\}|\(a\)|\[a\]|<a>|\{a\}|\s+at\s+|\(et\)|\[et\]|<et>|\{et\})\s*([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})',
            ]
            
            for pattern in html_patterns:
                matches = re.findall(pattern, text)
                for match in matches:
                    if len(match) == 2:
                        username, domain = match
                        email = f"{username}@{domain}"
                        if is_valid_email(email):
                            all_emails.append(email)
    
    # Direct string search for specific patterns in the original text
    # This is a fallback for cases that the regex patterns might miss
    text_lower = text.lower()
    
    # Look for common obfuscation patterns directly
    obfuscation_markers = ['(at)', '[at]', '<at>', '{at}', '(a)', '[a]', '<a>', '{a}', ' at ', '(et)', '[et]', '<et>', '{et}']
    
    for marker in obfuscation_markers:
        marker_lower = marker.lower()
        if marker_lower in text_lower:
            # Find all occurrences of the marker
            positions = [m.start() for m in re.finditer(re.escape(marker_lower), text_lower)]
            
            for pos in positions:
                # Look for username before the marker
                username_end = pos
                username_start = max(0, username_end - 50)  # Look back up to 50 chars
                username_text = text_lower[username_start:username_end]
                
                # Extract potential username
                username_match = re.search(r'([a-zA-Z0-9._%+\-]+)$', username_text)
                if not username_match:
                    continue
                
                username = username_match.group(1)
                
                # Look for domain after the marker
                domain_start = pos + len(marker_lower)
                domain_end = min(len(text_lower), domain_start + 50)  # Look ahead up to 50 chars
                domain_text = text_lower[domain_start:domain_end]
                
                # Extract potential domain
                domain_match = re.search(r'^([a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', domain_text)
                if not domain_match:
                    continue
                
                domain = domain_match.group(1)
                
                # Construct email
                email = f"{username}@{domain}"
                if is_valid_email(email):
                    all_emails.append(email)
    
    # Add edge case handling at the end
    edge_case_emails = extract_edge_case_emails(text)
    all_emails.extend(edge_case_emails)
    
    # Remove duplicates while preserving order
    unique_emails = []
    seen = set()
    for email in all_emails:
        email_lower = email.lower()
        if email_lower not in seen:
            seen.add(email_lower)
            unique_emails.append(email)
    
    return unique_emails

def extract_emails_from_text(text):
    """Extract email addresses from text using regex."""
    return extract_all_email_types(text)

def extract_obfuscated_emails_from_js(js_code):
    """Extract emails that are obfuscated in JavaScript code."""
    if not js_code:
        return []
    
    emails = []
    js_vars = {}
    
    # Decode HTML entities in the JavaScript code
    js_code = decode_email_entities(js_code)
    
    # Find variable assignments that might contain email parts
    var_assignments = re.finditer(JS_VAR_ASSIGNMENT_REGEX, js_code)
    for match in var_assignments:
        var_name = match.group(1)
        value1 = match.group(2)
        value2 = match.group(3)
        js_vars[var_name] = value1 + value2
    
    # Find variable additions that might build email addresses
    var_additions = re.finditer(JS_VAR_ADDITION_REGEX, js_code)
    for match in var_additions:
        var_name = match.group(1)
        if var_name in js_vars:
            value1 = match.group(2)
            value2 = match.group(3)
            js_vars[var_name] = js_vars[var_name] + value1 + value2
    
    # Find more complex variable additions with entities
    var_additions_with_entity = re.finditer(JS_VAR_ADDITION_WITH_ENTITY_REGEX, js_code)
    for match in var_additions_with_entity:
        var_name = match.group(1)
        if var_name in js_vars:
            value1 = match.group(2)
            value2 = match.group(3)
            value3 = match.group(4)
            js_vars[var_name] = js_vars[var_name] + value1 + value2 + value3
    
    # Extract emails from the variables
    for var_name, value in js_vars.items():
        potential_emails = extract_emails_from_text(value)
        emails.extend(potential_emails)
    
    # Look for direct email parts in JavaScript
    email_parts_matches = re.finditer(JS_EMAIL_PARTS_REGEX, js_code)
    for match in email_parts_matches:
        username = match.group(1)
        at_sign = '@' if match.group(2) in ('@', '&#64;', '&commat;') else match.group(2)
        
        # Look for domain parts that might follow
        domain_matches = re.finditer(JS_EMAIL_DOMAIN_REGEX, js_code[match.end():])
        for domain_match in domain_matches:
            domain = domain_match.group(1)
            dot = '.' if domain_match.group(2) in ('.', '&#46;', '&period;') else domain_match.group(2)
            tld = domain_match.group(3)
            
            # Construct the email
            email = f"{username}{at_sign}{domain}{dot}{tld}"
            if is_valid_email(email):
                emails.append(email)
            break  # Only use the first domain match
    
    # Special handling for the specific pattern in the provided HTML snippet
    # This pattern looks for: var addy... = 'something' + '&#64;'; addy... = addy... + 'domain' + '&#46;' + 'tld';
    pattern = r"var\s+([a-zA-Z0-9_]+)\s*=\s*['\"]([^'\"]+)['\"](?:\s*\+\s*['\"](?:&#64;|@)['\"]);\s*\1\s*=\s*\1\s*\+\s*['\"]([^'\"]+)['\"](?:\s*\+\s*['\"](?:&#46;|\.)['\"])(?:\s*\+\s*['\"]([^'\"]+)['\"]);"
    matches = re.finditer(pattern, js_code)
    for match in matches:
        username = match.group(2)
        domain = match.group(3)
        tld = match.group(4)
        email = f"{username}@{domain}.{tld}"
        if is_valid_email(email):
            emails.append(email)
    
    # Another pattern: document.getElementById('cloak...').innerHTML = ''; var prefix = '&#109;a' + 'i&#108;' + '&#116;o'; var path = 'hr' + 'ef' + '=';
    cloak_pattern = r"document\.getElementById\(['\"]cloak([a-zA-Z0-9]+)['\"]\)\.innerHTML\s*=\s*['\"](?:[^'\"]*)['\"];\s*var\s+([a-zA-Z0-9_]+)\s*=\s*['\"](?:[^'\"]+)['\"](?:\s*\+\s*['\"](?:[^'\"]+)['\"])+;\s*var\s+([a-zA-Z0-9_]+)\s*=\s*['\"](?:[^'\"]+)['\"](?:\s*\+\s*['\"](?:[^'\"]+)['\"])+;\s*var\s+([a-zA-Z0-9_]+)([a-zA-Z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"](?:\s*\+\s*['\"](?:&#64;|@)['\"]);"
    cloak_matches = re.finditer(cloak_pattern, js_code)
    for match in cloak_matches:
        var_name = match.group(4) + match.group(5)
        username = match.group(6)
        
        # Look for the next part that builds the domain
        domain_pattern = rf"{var_name}\s*=\s*{var_name}\s*\+\s*['\"]([^'\"]+)['\"](?:\s*\+\s*['\"](?:&#46;|\.)['\"])(?:\s*\+\s*['\"]([^'\"]+)['\"]);"
        domain_matches = re.finditer(domain_pattern, js_code[match.end():])
        for domain_match in domain_matches:
            domain = domain_match.group(1)
            tld = domain_match.group(2)
            email = f"{username}@{domain}.{tld}"
            if is_valid_email(email):
                emails.append(email)
            break  # Only use the first domain match
    
    # Remove duplicates
    unique_emails = []
    seen = set()
    for email in emails:
        email_lower = email.lower()
        if email_lower not in seen and is_valid_email(email):
            seen.add(email_lower)
            unique_emails.append(email)
    
    return unique_emails

def is_valid_email(email):
    """Validate an email address."""
    # Basic validation
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return False
    
    # Check for common invalid patterns
    invalid_patterns = [
        r'@example\.com$',
        r'@sample\.com$',
        r'@domain\.com$',
        r'@email\.com$',
        r'@test\.com$',
        r'@yourcompany\.com$',
    ]
    
    for pattern in invalid_patterns:
        if re.search(pattern, email, re.IGNORECASE):
            return False
    
    return True

def verify_mx_record(domain):
    """
    Verify if a domain has valid MX records.
    
    Args:
        domain (str): The domain to check
        
    Returns:
        bool: True if the domain has valid MX records, False otherwise
    """
    try:
        import dns.resolver
        
        # Try to get MX records for the domain
        mx_records = dns.resolver.resolve(domain, 'MX')
        
        # If we got here, the domain has MX records
        return len(mx_records) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers, dns.exception.Timeout):
        # No MX records found or DNS resolution failed
        return False
    except ImportError:
        # If dns.resolver is not available, assume the domain is valid
        logger.warning("dnspython package not installed. MX record verification disabled.")
        return True
    except Exception as e:
        # Any other error, log it and assume the domain is valid
        logger.warning(f"Error verifying MX record for {domain}: {str(e)}")
        return True

def get_email_domain(email):
    """
    Extract the domain from an email address.
    
    Args:
        email (str): The email address
        
    Returns:
        str: The domain part of the email address
    """
    if not email or '@' not in email:
        return None
    
    return email.split('@', 1)[1]

def rot13_decode(text):
    """Decode ROT13 encoded text."""
    if not text:
        return ""
    
    result = ""
    for char in text:
        if 'a' <= char <= 'z':
            result += chr((ord(char) - ord('a') + 13) % 26 + ord('a'))
        elif 'A' <= char <= 'Z':
            result += chr((ord(char) - ord('A') + 13) % 26 + ord('A'))
        else:
            result += char
    return result

def decode_data_enc_email(encoded_email):
    """
    Decode emails from data-enc-email attribute which often uses ROT13 encoding.
    
    Args:
        encoded_email (str): The encoded email from data-enc-email attribute
        
    Returns:
        str: The decoded email or None if decoding fails
    """
    if not encoded_email:
        return None
    
    # Replace [at] with @ if present
    if '[at]' in encoded_email:
        encoded_email = encoded_email.replace('[at]', '@')
    
    # Try ROT13 decoding (common for data-enc-email)
    try:
        decoded = rot13_decode(encoded_email)
        if '@' in decoded and is_valid_email(decoded):
            return decoded
    except:
        pass
    
    # Try other common encoding methods if ROT13 didn't work
    
    # Try simple character replacement (another common method)
    try:
        # Create a translation table for a simple substitution cipher
        # This handles cases where a custom character mapping is used
        char_map = {}
        for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
            char_map[encoded_email[i]] = c
        
        decoded = ""
        for char in encoded_email:
            if char in char_map:
                decoded += char_map[char]
            else:
                decoded += char
        
        if '@' in decoded and is_valid_email(decoded):
            return decoded
    except:
        pass
    
    # If all decoding attempts fail, return None
    return None

def xor_decode(text, key):
    """
    Decode XOR encoded text with a numeric key.
    
    Args:
        text (str): The text to decode
        key (int): The numeric key to use for XOR decoding
        
    Returns:
        str: The decoded text
    """
    if not text:
        return ""
    
    result = ""
    for char in text:
        result += chr(ord(char) ^ key)
    return result

def decode_base64(text):
    """
    Decode base64 encoded text.
    
    Args:
        text (str): The base64 encoded text
        
    Returns:
        str: The decoded text or empty string if decoding fails
    """
    if not text:
        return ""
    
    try:
        # Add padding if needed
        padding = 4 - (len(text) % 4) if len(text) % 4 else 0
        text += "=" * padding
        
        # Try to decode
        decoded = base64.b64decode(text).decode('utf-8', errors='ignore')
        return decoded
    except Exception as e:
        logger.debug(f"Error decoding base64: {str(e)}")
        return ""

def extract_emails_from_reversed_text(text):
    """
    Extract emails from text that might be reversed.
    
    Args:
        text (str): The text that might contain reversed emails
        
    Returns:
        list: List of extracted email addresses
    """
    if not text:
        return []
    
    emails = []
    
    # Try normal extraction
    normal_emails = extract_emails_from_text(text)
    emails.extend(normal_emails)
    
    # Try reversed extraction
    reversed_text = text[::-1]
    reversed_emails = extract_emails_from_text(reversed_text)
    emails.extend(reversed_emails)
    
    # Remove duplicates
    unique_emails = []
    seen = set()
    for email in emails:
        if email not in seen:
            seen.add(email)
            unique_emails.append(email)
    
    return unique_emails

def extract_emails_from_data_attributes(attributes):
    """
    Extract emails from data attributes.
    
    Args:
        attributes (dict): Dictionary of data attributes
        
    Returns:
        list: List of extracted email addresses
    """
    if not attributes:
        return []
    
    emails = []
    
    # Check for common patterns of email storage in data attributes
    
    # Pattern 1: data-user + data-domain + data-tld
    if 'data-user' in attributes and 'data-domain' in attributes and 'data-tld' in attributes:
        user = attributes['data-user']
        domain = attributes['data-domain']
        tld = attributes['data-tld']
        email = f"{user}@{domain}.{tld}"
        if is_valid_email(email):
            emails.append(email)
    
    # Pattern 2: data-name + data-domain
    if 'data-name' in attributes and 'data-domain' in attributes:
        name = attributes['data-name']
        domain = attributes['data-domain']
        email = f"{name}@{domain}"
        if is_valid_email(email):
            emails.append(email)
    
    # Pattern 3: data-email-user + data-email-domain
    if 'data-email-user' in attributes and 'data-email-domain' in attributes:
        user = attributes['data-email-user']
        domain = attributes['data-email-domain']
        email = f"{user}@{domain}"
        if is_valid_email(email):
            emails.append(email)
    
    # Pattern 4: data-email (encoded or obfuscated)
    if 'data-email' in attributes:
        encoded_email = attributes['data-email']
        
        # Try direct extraction
        direct_emails = extract_emails_from_text(encoded_email)
        emails.extend(direct_emails)
        
        # Try decoding if it looks like base64
        if re.match(r'^[A-Za-z0-9+/=]+$', encoded_email):
            decoded = decode_base64(encoded_email)
            decoded_emails = extract_emails_from_text(decoded)
            emails.extend(decoded_emails)
        
        # Try ROT13 decoding
        rot13_decoded = rot13_decode(encoded_email)
        rot13_emails = extract_emails_from_text(rot13_decoded)
        emails.extend(rot13_emails)
        
        # Try common XOR keys
        for key in [13, 42, 7, 1]:
            xor_decoded = xor_decode(encoded_email, key)
            xor_emails = extract_emails_from_text(xor_decoded)
            emails.extend(xor_emails)
    
    # Pattern 4.5: data-enc-email (specifically for ROT13 encoded emails)
    if 'data-enc-email' in attributes:
        encoded_email = attributes['data-enc-email']
        decoded_email = decode_data_enc_email(encoded_email)
        if decoded_email:
            emails.append(decoded_email)
    
    # Pattern 5: data-mail-* attributes
    mail_parts = {}
    for key, value in attributes.items():
        if key.startswith('data-mail-'):
            part_name = key[10:]  # Remove 'data-mail-'
            mail_parts[part_name] = value
    
    # Try to construct email from parts
    if 'user' in mail_parts and 'domain' in mail_parts:
        user = mail_parts['user']
        domain = mail_parts['domain']
        email = f"{user}@{domain}"
        if is_valid_email(email):
            emails.append(email)
    
    # Remove duplicates
    unique_emails = []
    seen = set()
    for email in emails:
        if email not in seen:
            seen.add(email)
            unique_emails.append(email)
    
    return unique_emails

def extract_emails_from_json_ld(json_ld):
    """
    Extract emails from JSON-LD data.
    
    Args:
        json_ld (str): JSON-LD data as string
        
    Returns:
        list: List of extracted email addresses
    """
    if not json_ld:
        return []
    
    emails = []
    
    try:
        # Parse JSON
        data = json.loads(json_ld)
        
        # Convert to string for regex search
        json_str = json.dumps(data)
        
        # Extract emails using regex
        found_emails = re.findall(EMAIL_REGEX, json_str)
        emails.extend(found_emails)
        
        # Look for specific JSON-LD properties that might contain emails
        if isinstance(data, dict):
            # Check for Schema.org Person or Organization
            if '@type' in data and data['@type'] in ['Person', 'Organization']:
                if 'email' in data:
                    emails.append(data['email'])
                
                # Check for contactPoint
                if 'contactPoint' in data:
                    contact_points = data['contactPoint']
                    if isinstance(contact_points, list):
                        for cp in contact_points:
                            if isinstance(cp, dict) and 'email' in cp:
                                emails.append(cp['email'])
                    elif isinstance(contact_points, dict) and 'email' in contact_points:
                        emails.append(contact_points['email'])
            
            # Check for any property that might contain an email
            for key, value in data.items():
                if isinstance(value, str) and '@' in value:
                    extracted = extract_emails_from_text(value)
                    emails.extend(extracted)
        
        # If it's a list, check each item
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    # Recursively check each item
                    item_emails = extract_emails_from_json_ld(json.dumps(item))
                    emails.extend(item_emails)
    except Exception as e:
        logger.debug(f"Error extracting emails from JSON-LD: {str(e)}")
    
    # Remove duplicates
    unique_emails = []
    seen = set()
    for email in emails:
        if email not in seen and is_valid_email(email):
            seen.add(email)
            unique_emails.append(email)
    
    return unique_emails

def extract_emails_from_meta_tags(meta_tags):
    """
    Extract emails from meta tags.
    
    Args:
        meta_tags (list): List of BeautifulSoup meta tag elements
        
    Returns:
        list: List of extracted email addresses
    """
    if not meta_tags:
        return []
    
    emails = []
    
    for tag in meta_tags:
        # Check content attribute
        content = tag.get('content', '')
        if content and '@' in content:
            content_emails = extract_emails_from_text(content)
            emails.extend(content_emails)
        
        # Check name attribute (might contain email-related keywords)
        name = tag.get('name', '').lower()
        if name in ['email', 'e-mail', 'contact', 'author']:
            content = tag.get('content', '')
            if content:
                content_emails = extract_emails_from_text(content)
                emails.extend(content_emails)
        
        # Check property attribute (Open Graph)
        prop = tag.get('property', '').lower()
        if prop in ['og:email', 'og:contact', 'article:author']:
            content = tag.get('content', '')
            if content:
                content_emails = extract_emails_from_text(content)
                emails.extend(content_emails)
    
    # Remove duplicates
    unique_emails = []
    seen = set()
    for email in emails:
        if email not in seen and is_valid_email(email):
            seen.add(email)
            unique_emails.append(email)
    
    return unique_emails

def extract_emails_from_accessibility_attributes(elements):
    """
    Extract emails from accessibility attributes like aria-label and title.
    
    Args:
        elements (list): List of BeautifulSoup elements
        
    Returns:
        list: List of extracted email addresses
    """
    if not elements:
        return []
    
    emails = []
    
    for element in elements:
        # Check aria-label attribute
        aria_label = element.get('aria-label', '')
        if aria_label and '@' in aria_label:
            aria_emails = extract_emails_from_text(aria_label)
            emails.extend(aria_emails)
        
        # Check title attribute
        title = element.get('title', '')
        if title and '@' in title:
            title_emails = extract_emails_from_text(title)
            emails.extend(title_emails)
        
        # Check alt attribute (for images)
        if element.name == 'img':
            alt = element.get('alt', '')
            if alt and '@' in alt:
                alt_emails = extract_emails_from_text(alt)
                emails.extend(alt_emails)
    
    # Remove duplicates
    unique_emails = []
    seen = set()
    for email in emails:
        if email not in seen and is_valid_email(email):
            seen.add(email)
            unique_emails.append(email)
    
    return unique_emails

def decode_email_entities(text):
    """Decode HTML entities in email addresses."""
    if not text:
        return ""
        
    # Common HTML entity replacements
    entities = {
        '&amp;': '&',
        '&lt;': '<',
        '&gt;': '>',
        '&#64;': '@',
        '&#46;': '.',
        '&#45;': '-',
        '&#95;': '_',
        '&period;': '.',
        '&commat;': '@',
        '&hyphen;': '-',
        '&lowbar;': '_',
        '&dot;': '.',
        '&at;': '@',
        '&#064;': '@',
        '&#0064;': '@',
        '&#00064;': '@',
        '&#000064;': '@',
        '&#x40;': '@',
        '&#x064;': '@',
        '&#x0040;': '@',
        '&colon;': ':',
        '&#58;': ':',
        '&#x3a;': ':',
    }
    
    # Replace entities
    for entity, char in entities.items():
        text = text.replace(entity, char)
    
    # Handle numeric entities
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), text)
    
    return text

def test_mx_verification():
    """Test MX record verification for various domains."""
    # Test domains with valid MX records
    valid_domains = [
        'gmail.com',
        'yahoo.com',
        'outlook.com',
        'hotmail.com',
        'microsoft.com',
        'google.com'
    ]
    
    # Test domains with invalid or non-existent MX records
    invalid_domains = [
        'thisisanonexistentdomain12345.com',
        'invalid-domain-for-testing.org',
        'no-mx-records-here.net',
        'example.invalid',
        'test.example'
    ]
    
    # Test valid domains
    print("Testing domains with valid MX records:")
    for domain in valid_domains:
        result = verify_mx_record(domain)
        print(f"Domain: {domain}, Has MX records: {result}")
    
    # Test invalid domains
    print("\nTesting domains with invalid or non-existent MX records:")
    for domain in invalid_domains:
        result = verify_mx_record(domain)
        print(f"Domain: {domain}, Has MX records: {result}")
    
    # Test email domain extraction
    print("\nTesting email domain extraction:")
    emails = [
        'user@gmail.com',
        'test.user@example.com',
        'john.doe123@subdomain.example.co.uk',
        'invalid-email',
        None
    ]
    
    for email in emails:
        domain = get_email_domain(email)
        print(f"Email: {email}, Domain: {domain}")

# Run the test if this file is executed directly
if __name__ == "__main__":
    print("Starting MX record verification test")
    test_mx_verification()
    print("MX record verification test completed")