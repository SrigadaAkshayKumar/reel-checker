"""Drives the debug APK on an emulator against a real backend (CI `android-emulator` job).

  python android/ci/emulator_smoke.py <app-debug.apk> <out dir> [backend log]

1. Launch: the main screen shows, an anonymous account is created (allowance line).
2. Share a reel link to the app, as Instagram's Share sheet does: the check runs on the backend and ends in a
   report or "share the file" (GitHub's runners are usually refused by Instagram), never a crash.
3. Floating button: turn it on, tap the dot over the home screen, type a link, check, see the result card.
Screenshots, UI dumps and logcat go to <out dir>. Fails on any crash or a missing screen.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

PKG = "org.reelcheck.app.debug"
LINK = "https://www.instagram.com/reel/C0deAbc123/"
FINISHED = re.compile(r"share the file|choose the video|Likely old footage|No contradiction found|Unverified|"
                      r"Debunked|Try again|Come back tomorrow|Watch a short ad", re.I)

apk, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)


def adb(*args: str, check: bool = True) -> str:
    res = subprocess.run(["adb", *args], capture_output=True, text=True, timeout=120)
    if check and res.returncode != 0:
        raise SystemExit(f"adb {' '.join(args)} failed: {res.stderr or res.stdout}")
    return res.stdout


def shot(name: str) -> None:
    (out / f"{name}.png").write_bytes(subprocess.run(["adb", "exec-out", "screencap", "-p"],
                                                     capture_output=True, timeout=60).stdout)


def ui(name: str = "ui") -> str:
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml", check=False)
    xml = adb("shell", "cat", "/sdcard/ui.xml", check=False)
    (out / f"{name}.xml").write_text(xml)
    return xml


def nodes(xml: str):
    for m in re.finditer(r"<node [^>]*>", xml):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(0)))
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", attrs.get("bounds", "[0,0][0,0]")))
        attrs["center"] = ((x1 + x2) // 2, (y1 + y2) // 2)
        yield attrs


def tap(x: int, y: int) -> None:
    adb("shell", "input", "tap", str(x), str(y))


def tap_text(label: str, xml: str | None = None) -> None:
    for n in nodes(xml or ui()):
        if n.get("text") == label or n.get("content-desc") == label:
            return tap(*n["center"])
    raise SystemExit(f"no '{label}' on screen; see {out}/ui.xml")


def screen_text(xml: str) -> str:
    return " | ".join(t for n in nodes(xml) for t in (n.get("text"), n.get("content-desc")) if t)


def diagnose(xml: str) -> None:
    """CI artifacts need a login to download: put what matters in the job log."""
    print("screen:", screen_text(xml)[:2000])
    backend = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    if backend and backend.is_file():
        print("backend log tail:\n" + "\n".join(backend.read_text().splitlines()[-30:]))
    log = adb("logcat", "-d", "-v", "brief", check=False)
    mine = [line for line in log.splitlines() if "reelcheck" in line or "AndroidRuntime" in line or " E/" in line]
    print("logcat (app and errors):\n" + "\n".join(mine[-60:]))


def wait_for(pattern: re.Pattern, name: str, seconds: int = 200) -> str:
    deadline = time.time() + seconds
    xml = ""
    while time.time() < deadline:
        xml = ui(name)
        if pattern.search(xml):
            return xml
        crash()
        time.sleep(2)
    shot(name)
    diagnose(xml)
    raise SystemExit(f"timed out waiting for {pattern.pattern!r}; see {out}/{name}.xml")


def crash() -> None:
    log = adb("logcat", "-d", check=False)
    (out / "logcat.txt").write_text(log)
    if "FATAL EXCEPTION" in log or f"ANR in {PKG}" in log:
        i = log.find("FATAL EXCEPTION")
        raise SystemExit("app crashed:\n" + log[max(i, 0):max(i, 0) + 4000])


adb("install", "-r", "-g", apk)  # -g grants runtime permissions (notifications)
adb("logcat", "-c")
adb("shell", "settings", "put", "global", "window_animation_scale", "0", check=False)

# 1. Launch
adb("shell", "am", "start", "-W", "-n", f"{PKG}/org.reelcheck.app.MainActivity")
wait_for(re.compile(r"free today|earned|free check is used"), "1-main")
shot("1-main")
print("1. main screen and anonymous account: ok")

# 2. Share sheet
adb("shell", "am", "start", "-W", "-a", "android.intent.action.SEND", "-t", "text/plain", "--es",
    "android.intent.extra.TEXT", f"Look at this {LINK}?igsh=abc", "-n", f"{PKG}/org.reelcheck.app.ShareReceiverActivity")
xml = wait_for(FINISHED, "2-shared")
shot("2-shared")
print("2. shared link checked:", FINISHED.search(xml).group(0))

# 3. Floating button: allow the overlay, switch it on (and over every app: no usage access on the emulator)
adb("shell", "appops", "set", PKG, "SYSTEM_ALERT_WINDOW", "allow")
adb("shell", "am", "start", "-W", "-n", f"{PKG}/org.reelcheck.app.MainActivity")
for _ in range(4):  # scroll to the settings card
    adb("shell", "input", "swipe", "500", "1500", "500", "400", "300")
time.sleep(1)
switches = [n for n in nodes(ui("3-settings")) if n.get("checkable") == "true"]
if len(switches) < 2:
    shot("3-settings")
    raise SystemExit("floating button switches not found")
tap(*switches[1]["center"])  # "Show the button over every app"
tap(*switches[0]["center"])  # "Floating check button"
time.sleep(3)
crash()
adb("shell", "input", "keyevent", "KEYCODE_HOME")
time.sleep(2)
shot("3-dot")

size = re.search(r"(\d+)x(\d+)", adb("shell", "wm", "size")).groups()
density = int(re.search(r"(\d+)\s*$", adb("shell", "wm", "density").strip()).group(1)) / 160
width = int(size[0])
tap(int(width - (8 + 26) * density), int(300 + 26 * density))  # the dot's default place (OverlayService)
xml = wait_for(re.compile("Check this reel"), "4-input", 20)
shot("4-input")
field = next(n for n in nodes(xml) if n.get("class") == "android.widget.EditText")
tap(*field["center"])
adb("shell", "input", "text", LINK)
tap_text("Check")
xml = wait_for(FINISHED, "5-result")
shot("5-result")
crash()
print("3. floating button: dot, input card, result card:", FINISHED.search(xml).group(0))
print("All good.")
