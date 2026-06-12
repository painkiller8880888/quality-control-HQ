import sys
import argparse
from pywinauto.application import Application
from dotenv import load_dotenv

load_dotenv()

    ERP_PASS = os.getenv("ERP_PASS")
    ERP_ID = os.getenv("ERP_ID")
