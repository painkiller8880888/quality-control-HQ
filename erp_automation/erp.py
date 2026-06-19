import os
import sys
import argparse
import time
import psutil
from pywinauto.application import Application
from dotenv import load_dotenv
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="ERP自動操作モジュール")
    parser.add_argument("csv_path", help="出力する構成CSVのパス")
    args = parser.parse_args()

    app = erp_login()
    csv_path = args.csv_path

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

    # フォームのツールバーが表示されるまで待機
    toolbar = wait_control(wnd1, auto_id="TOOLBAR")
    click_button(toolbar, found_index=3) #出力ボタンを押下

    # ファイル出力対象選択フォームが表示されるまで待機
    wnd2 = wait_control(wnd1, auto_id="frmMain")
    wnd3 = wait_control(wnd2, auto_id="pnlBottom")
    click_button(wnd3, auto_id="btnCsv") #CSV出力ボタンを押下

    #ファイル選択ダイアログが表示されるまで待機
    wnd4 = wait_control(wnd2, title="名前を付けて保存")

    #ファイル名入力欄が表示されるまで待機
    wnd5 = wait_control(wnd4, class_name='DUIViewWndClassName')
    wnd5 = wait_control(wnd5, auto_id="FileNameControlHost")
    set_edit(wnd5, auto_id='1001', text=csv_path) #ファイル名入力
    click_button(wnd4, auto_id="1") #保存ボタン押下
    
    #完了ダイアログが現れるまで待機
    if wait_csv_complete(csv_path):
        dlg = wait_control(wnd1, title="レベル別部品構成マスタリスト（正展開）")
        click_button(dlg, auto_id="2") #OKボタン押下
    else:
        time.sleep(5)

    wnd1.close()
    click_button(dlg, auto_id="6") #OKボタン押下

    if wait_for_process_exit(pid):
        main.close()
    else:
        print("timeout")
#    print(f"ERP Path: {args.erp_path}")
#    print(f"CSV Path: {args.csv_path}")

def erp_login():

    load_dotenv()
    parser = argparse.ArgumentParser(description="ERP自動操作モジュール")
    parser.add_argument("erp_path", help="ERP実行ファイルのパス")

    ERP_PASS = os.getenv("ERP_PASS")
    ERP_ID = os.getenv("ERP_ID")
    erp_path = args.erp_path

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

def wait_csv_complete(
    csv_path: str | Path,
    timeout: int = 600,
    check_interval: float = 2.0,
    stable_count: int = 3,
) -> bool:
    """
    CSVファイルの書き込み完了を待つ。

    Parameters
    ----------
    csv_path : str | Path
        CSVファイルのパス
    timeout : int
        最大待機時間（秒）
    check_interval : float
        サイズ確認間隔（秒）
    stable_count : int
        サイズが連続一致する回数

    Returns
    -------
    bool
        True: 出力完了
        False: タイムアウト
    """

    csv_path = Path(csv_path)

    start = time.time()
    prev_size = -1
    stable = 0

    while time.time() - start < timeout:

        if not csv_path.exists():
            time.sleep(check_interval)
            continue

        current_size = csv_path.stat().st_size

        if current_size == prev_size:
            stable += 1
            if stable >= stable_count:
                return True
        else:
            stable = 0
            prev_size = current_size

        time.sleep(check_interval)

    return False

def wait_for_process_exit(pid: int, timeout: float = 60.0, interval: float = 0.5) -> bool:
    """
    指定PIDのプロセス終了を待機する。

    Parameters
    ----------
    pid : int
        待機対象のPID
    timeout : float
        タイムアウト秒数
    interval : float
        ポーリング間隔

    Returns
    -------
    bool
        True: プロセス終了
        False: タイムアウト
    """

    start = time.time()

    while time.time() - start < timeout:
        if not psutil.pid_exists(pid):
            return True

        time.sleep(interval)

    return False

if __name__ == "__main__":
    main()
