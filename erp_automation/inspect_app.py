from pywinauto import Application
from pywinauto import Desktop
import psutil

app = Application(backend="uia").connect(title_re=".*レベル別.*")
pwnd = app.window(title_re=".*レベル別.*")
wnd1 = pwnd.child_window(title_re=".*ファイル出力.*")
wnd2 = wnd1.child_window(title_re=".*名前を付けて.*")
wnd3 = wnd2.child_window(class_name='DUIViewWndClassName')
wnd4 = wnd3.child_window(auto_id='FileNameControlHost')

for c in wnd4.children():
    ei = c.element_info
    print(
        f"{ei.control_type:10}",
        f"title={repr(ei.name)}",
        f"auto_id={ei.automation_id}",
        f"class={ei.class_name}"
    )


#wnd3.print_control_identifiers()
#dlg = app.window(title_re=".*レベル別.*")
#print(dlg.element_info.process_id)

#for p in psutil.process_iter(["pid", "ppid", "name"]):
#    print(
#        f"PID={p.info['pid']:5d} "
#        f"PPID={p.info['ppid']:5d} "
#        f"NAME={p.info['name']}"
 #   )