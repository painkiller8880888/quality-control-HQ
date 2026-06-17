from pywinauto import Desktop

def main():

    dump_parent_chain(auto_id="1001")

def dump_parent_chain(auto_id=None, title=None, process=None):
    """
    auto_id または title で対象コントロールを検索し、
    親階層をトップレベルまで表示する。
    さらに child_window() のコードを自動生成する。
    """

    desktop = Desktop(backend="uia")
    target = None

    # 全ウィンドウ検索
    for wnd in desktop.windows():
        if process and wnd.element_info.process_id != process:
            continue

        for ctrl in wnd.descendants():
            ei = ctrl.element_info

            if auto_id and ei.automation_id == auto_id:
                target = ctrl
                break

            if title and ei.name == title:
                target = ctrl
                break

        if target:
            break

    if target is None:
        print("Target Not Found")
        return

    # 親チェーン取得
    chain = []

    ctrl = target
    while ctrl:
        chain.append(ctrl)

        try:
            ctrl = ctrl.parent()
        except Exception:
            break

    chain.reverse()

    print("========== Parent Chain ==========")

    for i, ctrl in enumerate(chain):
        ei = ctrl.element_info

        print(
            f"[{i}] "
            f"{ei.control_type:12} "
            f"title={repr(ei.name):20} "
            f"auto_id={repr(ei.automation_id):15} "
            f"class={repr(ei.class_name)}"
        )

    print()
    print("========== child_window() ==========")

    print("ctrl = app.window(")

    top = chain[0].element_info

    if top.name:
        print(f'    title="{top.name}",')

    if top.automation_id:
        print(f'    auto_id="{top.automation_id}",')

    print(")")

    for c in chain[1:]:

        ei = c.element_info

        args = []

        if ei.name:
            args.append(f'title="{ei.name}"')

        if ei.automation_id:
            args.append(f'auto_id="{ei.automation_id}"')

        if ei.control_type:
            args.append(f'control_type="{ei.control_type}"')

        print(f"ctrl = ctrl.child_window({', '.join(args)})")

def show_parent_chain(auto_id=None, title=None, process=None):
    desktop = Desktop(backend="uia")

    # 検索
    target = None
    for w in desktop.windows():
        for c in w.descendants():
            ei = c.element_info

            if auto_id and ei.automation_id == auto_id:
                target = c
                break

            if title and ei.name == title:
                target = c
                break

        if target:
            break

    if target is None:
        print("Not Found")
        return

    print("=== Target ===")

    ctrl = target

    while ctrl:
        ei = ctrl.element_info

        print(
            f"{ei.control_type:12} "
            f"Title={repr(ei.name):20} "
            f"AutoId={repr(ei.automation_id):15} "
            f"Class={repr(ei.class_name):20} "
            f"PID={ei.process_id}"
        )

        try:
            ctrl = ctrl.parent()
        except Exception:
            break

if __name__ == "__main__":
    main()