"""
install_lisp_kernel.py
=========================
Registers the morris_lisp Jupyter kernel (lisp_kernel.py) so it shows up
in Jupyter's kernel picker / New menu, the same as "Python 3". Run once:

    python3 install_lisp_kernel.py

Re-run it any time (e.g. after moving this checkout to a different
path, or under a different Python environment) -- it always regenerates
the kernelspec from THIS script's own location and the CURRENT Python
interpreter (sys.executable), so it stays correct without hand-editing
any JSON. Installs into the current user's Jupyter data directory (no
admin/sudo needed, and it won't affect any other user on the machine) --
pass --system to install machine-wide instead, if you have permission to.

Uninstall with:
    jupyter kernelspec uninstall morris-lisp
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

from jupyter_client.kernelspec import KernelSpecManager

KERNEL_NAME = "morris-lisp"
DISPLAY_NAME = "morris_lisp"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system", action="store_true",
                         help="Install for all users on this machine instead of just the current one "
                              "(needs write access to the system Jupyter data directory).")
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    kernel_script = here / "lisp_kernel.py"
    if not kernel_script.exists():
        sys.exit("install_lisp_kernel.py: expected lisp_kernel.py next to this script, not found at %s"
                  % kernel_script)

    kernel_json = {
        "argv": [sys.executable, str(kernel_script), "-f", "{connection_file}"],
        "display_name": DISPLAY_NAME,
        "language": "scheme",
    }

    with tempfile.TemporaryDirectory() as tmp:
        spec_dir = Path(tmp) / KERNEL_NAME
        spec_dir.mkdir()
        (spec_dir / "kernel.json").write_text(json.dumps(kernel_json, indent=2))

        manager = KernelSpecManager()
        dest = manager.install_kernel_spec(
            str(spec_dir), kernel_name=KERNEL_NAME, user=not args.system)

    print("Installed the %r kernel (%s) at:\n  %s" % (DISPLAY_NAME, KERNEL_NAME, dest))
    print("Using interpreter: %s" % sys.executable)
    print('Pick "%s" from Jupyter\'s New menu / kernel picker to use it.' % DISPLAY_NAME)


if __name__ == "__main__":
    main()
