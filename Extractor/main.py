"""
Wrapper script for the Email Extractor.
This script allows running the Email Extractor with 'py main.py' from the Extractor directory.
"""

import sys
import os
import asyncio

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the main function from the email_extractor package
from email_extractor.main import main

if __name__ == "__main__":
    # Run the main function
    asyncio.run(main())