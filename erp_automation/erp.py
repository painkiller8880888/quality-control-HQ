import os
import sys
import argparse
from pywinauto.application import Application
from dotenv import load_dotenv

def main():
#    parser = argparse.ArgumentParser(description="ERP自動操作モジュール")
#    parser.add_argument("erp_path", help="ERP実行ファイルのパス")
#    parser.add_argument("csv_path", help="出力する構成CSVのパス")
#    args = parser.parse_args()
    app = erp_login()
#    print(f"ERP Path: {args.erp_path}")
#    print(f"CSV Path: {args.csv_path}")

def erp_login():
    load_dotenv()

    ERP_PASS = os.getenv("ERP_PASS")
    ERP_ID = os.getenv("ERP_ID")
    erp_path = "C:\ISKW01\ClientPack\RrrMen.exe"

    # ERP起動
    app = Application(backend="uia").start(erp_path)

    # ログイン画面が表示されるまで待機
    login = app.window(
        auto_id="Frm_Login",
        control_type="Window"
    )

    login.wait("visible", timeout=30)
    login.wait("enabled", timeout=30)

    # ユーザID入力
    login.child_window(
        auto_id="TxtUsrId",
        control_type="Edit"
    ).set_text(ERP_ID)

    # パスワード入力
    login.child_window(
        auto_id="TxtPasWd",
        control_type="Edit"
    ).set_text(ERP_PASS)

    # ログインボタン押下
    login.child_window(
        auto_id="btnLogin",
        control_type="Button"
    ).click_input()

if __name__ == "__main__":
    main()
