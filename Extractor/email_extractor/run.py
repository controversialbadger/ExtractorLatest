"""
Entry point for the Email Extractor.
Run this script with: python run.py
"""

import os
import sys

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import and run the main function from the main module
from email_extractor.main import main
import asyncio

if __name__ == "__main__":
    # Run the main function
    asyncio.run(main())