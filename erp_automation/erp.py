import os
import sys
import argparse
import time
import psutil
from pywinauto.application import Application
from dotenv import load_dotenv

def main():
#    parser = argparse.ArgumentParser(description="ERP自動操作モジュール")
#    parser.add_argument("erp_path", help="ERP実行ファイルのパス")
#    parser.add_argument("csv_path", help="出力する構成CSVのパス")
#    args = parser.parse_args()

    app = erp_login()
    csv_path = "C:\\Users\\P1569\\Desktop\\20260617.csv"

    # メインウィンドウが表示されるまで待機
    main = wait_window(app, auto_id="Frm_RrrMen")
    
    click_button(main, auto_id="btnTop13") #生産管理マスタボタン押下
    click_button(main, auto_id="btnSub03") #部品構成マスタボタン押下
    before = {p.pid for p in psutil.process_iter()}
    click_button(main, auto_id="btnPrg11") #レベル別部品構成マスタリスト(正展開)ボタン押下

    pid, app1, wnd1 = connect_new_window(
    before_pids=before,
    auto_id="FR_SSSMAIN"
    )
    print(pid)

    # フォームのツールバーが表示されるまで待機
    toolbar = wait_control(wnd1, auto_id="TOOLBAR")
    click_button(toolbar, found_index=3) #出力ボタンを押下

    # ファイル出力対象選択フォームが表示されるまで待機
    wnd2 = wait_control(wnd1, auto_id="pnlBottom")
    click_button(wnd2, auto_id="btnCsv") #CSV出力ボタンを押下

    #ファイル選択ダイアログが表示されるまで待機
    wnd3 = wnd1.child_window(title="ファイル出力対象項目選択", auto_id="frmMain", control_type="Window")
    wnd3 = wnd3.child_window(title="名前を付けて保存", control_type="Window")

    #ファイル名入力欄が表示されるまで待機
    wnd4 = wnd3.child_window(control_type="Pane")
    wnd4 = wnd3.child_window(title="ファイル名:", auto_id="FileNameControlHost", control_type="ComboBox")
    set_edit(wnd4, auto_id='1001', text=csv_path) #ファイル名入力
    click_button(wnd3, auto_id="1") #保存ボタン押下
    
#    print(f"ERP Path: {args.erp_path}")
#    print(f"CSV Path: {args.csv_path}")

def erp_login():
    load_dotenv()

    ERP_PASS = os.getenv("ERP_PASS")
    ERP_ID = os.getenv("ERP_ID")
    erp_path = "C:\\ISKW01\\ClientPack\\RrrMen.exe"

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
    set_edit(login, auto_id="TxtUsrId", text=ERP_ID)

    # パスワード入力
    set_edit(login, auto_id="TxtPasWd", text=ERP_PASS)

    # ログインボタン押下
    click_button(login, auto_id="btnLogin")

    return app

def set_edit(parent, auto_id, text, timeout=30):
    edit = parent.child_window(
        auto_id=auto_id,
        control_type="Edit"
    )

    edit.wait("visible", timeout=timeout)
    edit.wait("enabled", timeout=timeout)
    edit.set_text(text)

def click_button(parent, timeout=30, **kwargs):
    button = parent.child_window(
        control_type="Button",
        **kwargs
    )

    button.wait("visible", timeout=timeout)
    button.wait("enabled", timeout=timeout)
    button.click_input()

def wait_window(app, timeout=60, cpu_threshold=5, **kwargs):

    wnd = app.window(**kwargs)

    wnd.wait("visible", timeout=timeout)
    wnd.wait("enabled", timeout=timeout)

    app.wait_cpu_usage_lower(
        threshold=cpu_threshold,
        timeout=timeout
    )

    return wnd

def connect_new_window(before_pids, auto_id=None, title=None, timeout=60):

    end = time.time() + timeout

    while time.time() < end:

        current = {p.pid for p in psutil.process_iter()}
        new_pids = current - before_pids

        for pid in new_pids:

            try:
                app = Application(backend="uia").connect(process=pid)

                if auto_id:
                    wnd = app.window(auto_id=auto_id)
                else:
                    wnd = app.window(title=title)

                if wnd.exists(timeout=0.2):
                    wnd.wait("visible")
                    wnd.wait("enabled")
                    app.wait_cpu_usage_lower(threshold=5)

                    return pid, app, wnd

            except Exception:
                pass

        time.sleep(0.5)

    raise TimeoutError()

def wait_child(parent, timeout=60, **kwargs):

    ctrl = parent.child_window(**kwargs)

    ctrl.wait("visible", timeout=timeout)
    ctrl.wait("enabled", timeout=timeout)

    return ctrl

def wait_control(parent, timeout=60, deep=False, index=0, **kwargs):

    end = time.time() + timeout

    while time.time() < end:

        try:
            if deep:
                controls = parent.descendants(**kwargs)

                if len(controls) > index:
                    ctrl = controls[index]
                else:
                    ctrl = None

            else:
                ctrl = parent.child_window(**kwargs)

            if ctrl and ctrl.exists() and ctrl.is_visible() and ctrl.is_enabled():
                return ctrl

        except Exception:
            pass

        time.sleep(0.2)

    raise TimeoutError()

if __name__ == "__main__":
    main()
