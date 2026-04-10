import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app

# This file is needed for Vercel Serverless Functions to automatically detect the Flask app
