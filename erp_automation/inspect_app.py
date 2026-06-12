from pywinauto import Application

app = Application(backend="uia").connect(title_re=".*Login.*")

app.top_window().print_control_identifiers()