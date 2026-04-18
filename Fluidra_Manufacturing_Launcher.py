#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Fluidra Manufacturing Solution - Launcher
Version: 1.0
"""

import os
import sys
import traceback
import logging
from datetime import datetime

# Configure logging
def setup_logging():
    """Set up logging configuration."""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, f'fms_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

def main():
    """Main entry point for the application."""
    logger = setup_logging()
    
    try:
        logger.info("Starting Fluidra Manufacturing Solution...")
        
        # Check if required modules are installed
        try:
            import customtkinter as ctk
            import win32print
            import gspread
            from oauth2client.service_account import ServiceAccountCredentials
            from PIL import Image
        except ImportError as e:
            logger.error(f"Missing required module: {e}")
            input("Press Enter to exit...")
            return 1
        
        # Import the main application
        from Fluidra_Manufacturing_Solutionv7_4 import BarcodeApp
        
        # Create and run the application
        app = BarcodeApp()
        app.mainloop()
        
        return 0
        
    except Exception as e:
        logger.error(f"Unhandled exception: {str(e)}")
        logger.error(traceback.format_exc())
        input("An error occurred. Press Enter to exit...")
        return 1

if __name__ == "__main__":
    sys.exit(main())
