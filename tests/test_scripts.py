"""The start/stop scripts in scripts/: that they are well formed (shell and PowerShell syntax, plain ASCII, Unix
line endings, executable) and that the docs name them. It does not start the dashboard.

    python tests/test_scripts.py
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        check.failed = True


check.failed = False


def read(*parts):
    with open(os.path.join(ROOT, *parts), "rb") as f:
        return f.read()


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, **kw)


names = sorted(os.listdir(SCRIPTS)) if os.path.isdir(SCRIPTS) else []
need = {"_setup.sh", "pi-dashboard.sh", "mac-dashboard.sh", "windows-dashboard.bat", "windows-dashboard.ps1"}
check(f"scripts: all five are there {sorted(need - set(names))}", need <= set(names))

for n in names:
    data = read("scripts", n)
    check(f"{n}: plain ASCII (Windows PowerShell 5.1 reads a file without a byte-order mark as ANSI)",
          all(b < 128 for b in data))
    if n.endswith(".sh"):
        check(f"{n}: Unix line endings (a CRLF script fails on a Pi or a Mac)", b"\r" not in data)

shells = [n for n in names if n.endswith(".sh")]
bash = shutil.which("bash")
if bash:
    for n in shells:
        r = run([bash, "-n", os.path.join(SCRIPTS, n)])
        check(f"{n}: bash finds no syntax error {r.stderr.strip()[:80]}", r.returncode == 0)
else:
    print("skip bash syntax checks: no bash on this computer")

# The Pi and Mac scripts must be executable in Git, so scripts/pi-dashboard.sh works as written in the README.
git = shutil.which("git")
if git and os.path.isdir(os.path.join(ROOT, ".git")):
    listing = run([git, "ls-files", "-s", "scripts"], cwd=ROOT).stdout.splitlines()
    mode = {line.split("\t")[1].split("/")[-1]: line.split()[0] for line in listing if "\t" in line}
    for n in ("pi-dashboard.sh", "mac-dashboard.sh"):
        if n in mode:                                  # not committed yet: nothing to check
            check(f"{n}: executable in Git (mode {mode[n]})", mode[n] == "100755")
    attrs = read(".gitattributes").decode("ascii", "replace") if os.path.exists(os.path.join(ROOT, ".gitattributes")) else ""
    check(".gitattributes keeps *.sh on LF and *.bat on CRLF", "*.sh  text eol=lf" in attrs and "*.bat text eol=crlf" in attrs)

# PowerShell: the script parses (Windows PowerShell 5.1 or PowerShell 7, whichever is here).
ps = shutil.which("pwsh") or shutil.which("powershell")
if ps:
    ps1 = os.path.join(SCRIPTS, "windows-dashboard.ps1")
    r = run([ps, "-NoProfile", "-Command",
             "$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile("
             f"'{ps1}',[ref]$t,[ref]$e);$e|ForEach-Object{{$_.Message+' (line '+$_.Extent.StartLineNumber+')'}}"])
    check(f"windows-dashboard.ps1: PowerShell finds no syntax error {r.stdout.strip()[:80]}", r.returncode == 0 and not r.stdout.strip())
else:
    print("skip PowerShell syntax check: no PowerShell on this computer")

# The .bat hands over to the .ps1 beside it, and clears PSModulePath for that run (PowerShell 7 on the path makes 5.1 miss cmdlets).
bat = read("scripts", "windows-dashboard.bat").decode("ascii", "replace") if "windows-dashboard.bat" in names else ""
check("windows-dashboard.bat: runs windows-dashboard.ps1 beside it, for this run only",
      'windows-dashboard.ps1" %*' in bat and "-ExecutionPolicy Bypass" in bat and "setlocal" in bat and 'set "PSModulePath="' in bat)

# The help text works and an unknown command is refused, without touching anything.
if bash:
    for n in ("pi-dashboard.sh", "mac-dashboard.sh"):
        path = os.path.join(SCRIPTS, n)
        r = run([bash, path, "help"])
        check(f"{n}: help lists the commands", r.returncode == 0 and all(w in r.stdout for w in ("start", "stop", "status", "run")))
        r = run([bash, path, "no-such-command"])
        check(f"{n}: an unknown command is refused (exit 2)", r.returncode == 2 and "Unknown command" in r.stderr)
    r = run([bash, os.path.join(SCRIPTS, "pi-dashboard.sh"), "help"])
    check("pi-dashboard.sh: help has boot-off and boot-on", "boot-off" in r.stdout and "boot-on" in r.stdout)

# The docs name the scripts.
readme, pi = read("README.md").decode("utf-8"), read("README_Raspberry.md").decode("utf-8")
check("README: names the three scripts", all(s in readme for s in ("scripts/pi-dashboard.sh", "scripts/mac-dashboard.sh", "scripts\\windows-dashboard.bat")))
check("README_Raspberry: uses the Pi script (start, status, boot-off)", all(s in pi for s in ("pi-dashboard.sh start", "pi-dashboard.sh status", "pi-dashboard.sh boot-off")))
check("README: says what --dry does", "reads each controller's status" in readme)

sys.exit(1 if check.failed else 0)
