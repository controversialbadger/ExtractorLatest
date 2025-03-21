# Email Extractor

A powerful tool for extracting email addresses from websites with advanced features to ensure email deliverability.

## Features

- Extract emails from websites using both HTTP requests and browser automation (Playwright)
- Find and crawl contact pages automatically
- Handle JavaScript-heavy websites
- Detect and extract obfuscated email addresses
- Verify MX records to ensure email deliverability
- Support for multiple languages and regions

## Installation

1. Clone the repository
2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:

```bash
python -m playwright install
```

## Usage

Run the main script:

```bash
python email_extractor/main.py
```

Enter a URL when prompted, and the tool will extract email addresses from the website.

## Configuration

You can customize the behavior of the Email Extractor by modifying the settings in `email_extractor/config.py`:

- `VERIFY_MX_RECORDS`: Enable/disable MX record verification (default: True)
- `HTTP_TIMEOUT`: Timeout for HTTP requests in seconds
- `PLAYWRIGHT_TIMEOUT`: Timeout for Playwright operations in seconds
- `MAX_CONTACT_PAGES`: Maximum number of contact pages to check
- And many more...

## MX Record Verification

The Email Extractor now includes MX record verification to ensure email deliverability. This feature checks if the domain of each extracted email has valid MX records, which are required for receiving emails.

Benefits of MX record verification:
- Reduces bounced emails
- Improves email campaign deliverability
- Filters out invalid or non-existent domains
- Saves time by focusing on deliverable email addresses

To disable MX record verification, set `VERIFY_MX_RECORDS = False` in the config file.

## Dependencies

- requests: For HTTP requests
- beautifulsoup4: For HTML parsing
- playwright: For browser automation
- dnspython: For MX record verification
- tenacity: For retry logic
- tldextract: For domain extraction
- lxml: For HTML parsing