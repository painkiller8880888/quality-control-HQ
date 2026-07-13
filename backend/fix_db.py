import os
import subprocess
import sys


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def main():
    subprocess.check_call([sys.executable, "manage.py", "migrate"])


if __name__ == "__main__":
    main()
