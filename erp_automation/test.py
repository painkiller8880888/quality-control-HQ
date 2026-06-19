import sys
import argparse
from pywinauto.application import Application
from dotenv import load_dotenv

app = Application(backend="uia").connect(process=8280)
wnd1 = app.window(auto_id="FR_SSSMAIN")
wnd2 = wnd1.child_window(title="レベル別部品構成マスタリスト（正展開）")
btn = wnd2.child_window(auto_id="2")
btn.click_input()
