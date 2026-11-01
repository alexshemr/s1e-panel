"""First installation of S1E Panel on an Aqara S1E (NPD1121WSK01) over the service console (UART).

    python s1e_install.py --port COM5 --check
    python s1e_install.py --port COM5 --bundle s1e-panel-first-install.tar.gz --sums SHA256SUMS.txt
    python s1e_install.py --port COM5 --restore-factory-boot

What it does, in order (see docs/installation.md):
 1. Waits for the panel's bootloader (U-Boot) and stops it, saves the factory boot arguments to --log-dir.
 2. Boots the stock kernel once into a service shell (temporary arguments, nothing saved).
 3. Checks the hardware and the existing data volume. --check stops here and reboots to the stock firmware.
 4. Sends the first-install bundle over the console, verifies its SHA-256, unpacks it into a new folder
    /data/s1e-panel and verifies the signed application inside it.
 5. Boots S1E Panel once with the new boot arguments, still without saving them, and waits until the
    interface reports healthy.
 6. Only then saves the boot arguments (the factory value is kept as s1e_factory_bootargs) and starts the panel.

The factory root file system, kernel, partitions and bootloader stay untouched. Until step 6 a power cycle
returns the panel to the stock firmware. --restore-factory-boot puts the saved factory boot arguments back.

Needs Python 3.9+ and pyserial (pip install pyserial). The Wi-Fi password is never written to the log.
"""
import argparse
import base64
import datetime
import getpass
import hashlib
import json
import pathlib
import re
import sys
import tarfile
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial is missing: run  python -m pip install pyserial")

UBOOT_PROMPT, SHELL_PROMPT = b"SigmaStar # ", b"/ # "
# Partition layout of the NPD1121WSK01 board; the data volume (UBI) is mtd13.
PARTITIONS = ["BOOT0", "BOOT1", "ENV", "ENV1", "KEY_CUST", "KERNEL", "KERNEL_BAK", "rootfs", "rootfs_bak",
              "factory", "MISC", "RES", "RES_BAK", "UBI"]
BOOTSTRAP = "mount -a;mount -t ubifs ubi0:data /data;sh /data/s1e;exec /linuxrc"
BUNDLE_FILES = {"initial.s1e", "system/panel-update", "system/update-check", "system/update-public.pem",
                "system/init.sh", "system/app.sh", "system/network.sh", "system/dhcp.sh", "system/init-hardware.sh"}
MODULES = ["lcd_drv", "mhal", "mi_common", "mi_sys", "mi_gfx", "mi_disp", "mi_panel", "mi_fb", "bl_fdrv"]
UBOOT_LINE_LIMIT = 511          # the vendor U-Boot reads at most this many characters per command
CHUNK = 768                     # base64 characters per console line
ROOT, STAGE = "/data/s1e-panel", "/data/s1e-panel.installing"


class InstallError(Exception):
    pass


def say(text=""):
    print(text, flush=True)


def service_bootargs(original):
    """Factory arguments with a shell instead of the stock init: boots once, saves nothing."""
    return original.replace(" init=/linuxrc ", " init=/bin/sh ")


def panel_bootargs(original):
    """Factory arguments that mount the data volume and start S1E Panel, falling back to the stock init.

    Only the init and the console verbosity change (S1E Panel restores loglevel 3 itself); the root file
    system, partitions and hardware memory reservations stay exactly as the factory set them."""
    args = re.sub(r" loglevel=\d+(?= )", "", service_bootargs(original))
    return args + ' ubi.mtd=13 -- -c "' + BOOTSTRAP + '"'


def check_factory_bootargs(original):
    if "/data/s1e" in original:
        raise InstallError("S1E Panel already starts on this panel. Update it from Settings -> Panel update, "
                           "or use --restore-factory-boot first.")
    if original.count(" init=/linuxrc ") != 1 or "rootfstype=squashfs" not in original:
        raise InstallError("Unexpected boot arguments (no stock init=/linuxrc). Nothing was changed.")
    parts = re.search(r"mtdparts=nand0:(\S+)", original)
    names = re.findall(r"\(([^)]+)\)", parts.group(1)) if parts else []
    if names != PARTITIONS:
        raise InstallError("Unexpected flash layout %s. This installer supports the NPD1121WSK01 layout only. "
                           "Nothing was changed." % names)
    if len("setenv bootargs '" + panel_bootargs(original) + "'") > UBOOT_LINE_LIMIT:
        raise InstallError("The new boot arguments would not fit the bootloader's command line. Nothing was changed.")


def check_bundle(path, sums):
    if not path.is_file():
        raise InstallError(f"{path} not found")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if sums:
        listed = {}
        for line in pathlib.Path(sums).read_text(encoding="utf-8").splitlines():
            m = re.match(r"([0-9a-f]{64})\s+\*?(\S+)", line.strip())
            if m:
                listed[m.group(2)] = m.group(1)
        if listed.get(path.name) != digest:
            raise InstallError(f"{path.name}: SHA-256 does not match {pathlib.Path(sums).name}. Download it again.")
    if len(data) > 10 * 1024 * 1024:
        raise InstallError("The bundle is larger than the panel's RAM disk allows")
    with tarfile.open(path, "r:gz") as archive:
        names = {m.name.lstrip("./") for m in archive.getmembers()}
    missing = BUNDLE_FILES - names
    if missing:
        raise InstallError("Not a first-install bundle; missing " + ", ".join(sorted(missing)))
    return data, digest


class Console:
    """The panel's UART at 115200 baud. Everything received goes to the log; secrets are never sent through it."""

    def __init__(self, port, log):
        self.s = serial.Serial(port=None, baudrate=115200, timeout=0.02, xonxoff=False, rtscts=False, dsrdtr=False)
        self.s.dtr = self.s.rts = False
        self.s.port = port
        self.s.open()
        self.log = open(log, "ab")
        self.quiet = False

    def close(self):
        self.s.close()
        self.log.close()

    def read(self):
        data = self.s.read(min(self.s.in_waiting or 1, 65536))
        if data and not self.quiet:
            self.log.write(data)
            self.log.flush()
        return data

    def until(self, prompt, timeout):
        out, end = bytearray(), time.monotonic() + timeout
        while time.monotonic() < end:
            out.extend(self.read())
            if bytes(out[-300:]).replace(b"\r", b"").endswith(prompt):
                return out.decode("utf-8", "replace").replace("\r", "")
        raise InstallError("The panel stopped answering on the console (%s)" % prompt.decode().strip())

    def run(self, command, prompt=SHELL_PROMPT, timeout=15):
        self.s.write(command.encode("ascii") + b"\r")
        self.s.flush()
        return self.until(prompt, timeout)

    def shell(self, command, timeout=15):
        """Console text of one shell command. The echoed command line comes first: match lines, not substrings."""
        return self.run(command, SHELL_PROMPT, timeout)

    def value(self, command, timeout=15):
        """One value printed by a command: value("uname -r") -> "4.9.84"."""
        found = re.findall(r"^<<(.*)>>$", self.run(f'echo "<<$({command})>>"', SHELL_PROMPT, timeout), re.M)
        return found[-1].strip() if found else ""

    def has_line(self, command, line, timeout=15):
        return line in self.run(command, SHELL_PROMPT, timeout).split("\n")

    def bootloader(self, minutes=5):
        """Wait for U-Boot after the panel is powered or rebooted and stop it with Enter."""
        self.s.write(b"\r")
        try:
            return self.until(UBOOT_PROMPT, 1.5)
        except InstallError:
            pass
        out, state, last, end = bytearray(), "wait", 0.0, time.monotonic() + minutes * 60
        while time.monotonic() < end:
            out.extend(self.read())
            tail = bytes(out[-20000:]).replace(b"\r", b"")
            if tail.endswith(UBOOT_PROMPT):
                return tail.decode("utf-8", "replace")
            if state == "wait" and b"U-Boot" in tail:
                state = "stop"
            if state == "stop":
                if b"Starting kernel" in tail or b"NAND read:" in tail:
                    say("  The bootloader was not stopped in time. Power the panel off and on again "
                        "(see the guide for panels made after July 2023).")
                    out, state = bytearray(), "wait"
                elif time.monotonic() - last >= 0.01:
                    self.s.write(b"\r")
                    last = time.monotonic()
        raise InstallError("No bootloader on the console. Check the wiring (TX->RX, RX->TX, GND) and the port.")

    def env(self, name):
        text = self.run("printenv " + name, UBOOT_PROMPT).replace("\r", "")
        m = re.search(r"^" + re.escape(name) + r"=(.*)$", text, re.M)
        return m.group(1) if m else None

    def setenv(self, name, value):
        if "'" in value:
            raise InstallError("Unexpected quote in " + name)
        self.run(f"setenv {name} '{value}'", UBOOT_PROMPT)
        if self.env(name) != value:
            raise InstallError(f"The bootloader did not accept {name}. Nothing was saved.")

    def boot(self, prompt=SHELL_PROMPT, timeout=60):
        return self.run("run bootcmd", prompt, timeout)

    def set_rate(self, rate):
        """Switch both ends to a faster rate; a guard on the panel switches back if the PC does not answer."""
        self.run("(sleep 25; stty -F /dev/ttyS0 115200) & S1E_RATE_GUARD=$!")
        self.s.write(f"stty -F /dev/ttyS0 {rate}; sleep 1; echo S1E_RATE_READY\r".encode())
        self.s.flush()
        self.s.baudrate = rate
        try:
            if "S1E_RATE_READY" not in self.until(SHELL_PROMPT, 5):
                raise InstallError("rate probe lost")
            self.run("kill $S1E_RATE_GUARD; unset S1E_RATE_GUARD")
            probe = "0123456789abcdef" * 8
            if probe not in self.run("echo " + probe).split("\n"):
                raise InstallError("rate probe corrupted")
            return True
        except InstallError:
            time.sleep(26)
            self.s.baudrate = 115200
            self.s.write(b"\x15\r")
            self.until(SHELL_PROMPT, 5)
            return False

    def reset_rate(self):
        if self.s.baudrate != 115200:
            self.s.write(b"stty -F /dev/ttyS0 115200\r")
            self.s.flush()
            time.sleep(0.5)
            self.s.baudrate = 115200
            self.run("")

    def upload(self, data, destination):
        """Send a file in base64 lines and check its SHA-256 on the panel."""
        encoded = base64.b64encode(data).decode("ascii")
        self.run(f": > {destination}.b64")
        self.run("stty -F /dev/ttyS0 -echo")
        self.quiet = True
        started, total = time.monotonic(), len(encoded)
        try:
            for offset in range(0, total, CHUNK):
                self.run(f"printf '%s' '{encoded[offset:offset + CHUNK]}' >> {destination}.b64", timeout=10)
                if offset // CHUNK % 200 == 0:
                    done = offset / total
                    left = (time.monotonic() - started) / done * (1 - done) if done else 0
                    print(f"\r  {done * 100:5.1f} %  about {left / 60:.0f} min left   ", end="", flush=True)
        finally:
            self.quiet = False
            self.run("stty -F /dev/ttyS0 echo")
        say("\r  100.0 %                          ")
        self.run(f"base64 -d {destination}.b64 > {destination} && rm {destination}.b64", timeout=60)
        digest = hashlib.sha256(data).hexdigest()
        if digest not in self.shell(f"sha256sum {destination}"):
            raise InstallError("The bundle arrived damaged. Run the installer again.")

    def write_secret(self, content, destination):
        """Write a small private file without echo and without logging it."""
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        self.run("stty -F /dev/ttyS0 -echo")
        self.quiet = True
        try:
            self.run(f"umask 077; printf '%s' '{encoded}' | base64 -d > {destination}.next && "
                     f"chmod 600 {destination}.next && mv {destination}.next {destination}")
        finally:
            self.quiet = False
            self.run("stty -F /dev/ttyS0 echo")


def wpa_conf(ssid, password):
    """The same file the panel writes from Settings -> Wi-Fi."""
    if not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise InstallError("The Wi-Fi name must be 1-32 bytes")
    if not 8 <= len(password) <= 63 or any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise InstallError("The Wi-Fi password must be 8-63 printable characters (WPA2-PSK)")
    escaped = password.replace("\\", "\\\\").replace('"', '\\"')
    return ("ctrl_interface=/tmp/s1e-panel/run/wpa\nupdate_config=0\nnetwork={\n ssid=" +
            ssid.encode("utf-8").hex() + '\n psk="' + escaped + '"\n}\n')


def enter_service_shell(c, factory):
    c.setenv("bootargs", service_bootargs(factory))
    say("  Booting the stock kernel into a service shell (temporary, nothing saved)...")
    c.boot(SHELL_PROMPT, 60)
    if not re.search(r"^uid=0\(", c.shell("id"), re.M):
        raise InstallError("No root shell")
    c.run("[ -r /proc/mtd ] || mount -t proc proc /proc")
    c.run("[ -d /sys/class/mtd ] || mount -t sysfs sysfs /sys")
    if " /tmp tmpfs " not in c.shell("cat /proc/mounts"):
        c.run("mount -t tmpfs -o size=24m tmpfs /tmp")


def check_panel(c):
    """Read-only checks of the running stock system. Returns free space on the data volume in KiB."""
    kernel = c.value("uname -r")
    if kernel != "4.9.84":
        raise InstallError("Unexpected kernel %r; this release supports the stock 4.9.84 kernel" % kernel)
    if not re.search(r'^mtd13: \S+ \S+ "UBI"$', c.shell("cat /proc/mtd"), re.M):
        raise InstallError("Data partition mtd13 (UBI) not found")
    missing = [m for m in MODULES if not c.has_line(f"[ -f /lib/modules/4.9.84/{m}.ko ] && echo FOUND", "FOUND")]
    if missing:
        raise InstallError("Stock drivers missing: " + ", ".join(missing))
    if "m_wPanelPwGpioNum = 9" not in c.shell("cat /config/config.ini"):
        raise InstallError("Unexpected display configuration in /config/config.ini")
    if c.has_line("cat /sys/bus/sdio/devices/mmc*/vendor 2>/dev/null", "0x007a"):
        raise InstallError("This panel has the SSW102B Wi-Fi chip, which S1E Panel has not been tested with")
    if not re.search(r"^\S+ /data ubifs ", c.shell("cat /proc/mounts"), re.M):
        if not c.has_line("ubiattach /dev/ubi_ctrl -m 13 -d 1 && mount -t ubifs ubi1_0 /data && echo DATA_READY",
                          "DATA_READY", 30):
            raise InstallError("The data volume did not mount")
    c.run("mount -o remount,rw /data")
    m = re.search(r"\s(\d+)\s+(\d+)\s+(\d+)\s+\d+%\s+/data$", c.shell("df -k /data"), re.M)
    if not m:
        raise InstallError("Could not read free space on /data")
    return int(m.group(3))


def wait_healthy(c, minutes=4):
    """S1E Panel prints the console prompt early; poll the core until the interface is drawing."""
    end = time.monotonic() + minutes * 60
    while time.monotonic() < end:
        time.sleep(3)
        try:
            text = c.shell("printf '%s\\n' '{\"op\":\"health\"}' | /tmp/s1e-panel/bin/panelctl /tmp/s1e-panel/run/core.sock 2>/dev/null", 15)
        except InstallError:
            continue
        for line in text.splitlines():
            if line.startswith("{"):
                try:
                    if json.loads(line).get("ready") is True:
                        return c.value("cat /tmp/s1e-panel/run/ip 2>/dev/null")
                except ValueError:
                    pass
    raise InstallError("S1E Panel did not report a healthy start")


def reboot_to_bootloader(c):
    c.run("sync")
    c.s.write(b"reboot -f\r")
    c.s.flush()
    return c.bootloader(2)


def install(c, args, log_dir):
    data, digest = check_bundle(pathlib.Path(args.bundle), args.sums) if args.bundle else (b"", "")
    ssid = password = None
    if args.wifi_ssid and not args.check:
        ssid, password = args.wifi_ssid, getpass.getpass(f"Password for Wi-Fi '{args.wifi_ssid}': ")
        conf = wpa_conf(ssid, password)
    if args.bundle:
        say(f"Bundle {pathlib.Path(args.bundle).name}: {len(data) / 1048576:.1f} MiB, SHA-256 OK")

    say("\n[1/6] Waiting for the bootloader. Power the panel on now.")
    c.bootloader()
    factory = c.env("bootargs") or ""
    bootcmd = c.env("bootcmd") or ""
    check_factory_bootargs(factory)
    (log_dir / "boot-environment.json").write_text(json.dumps(
        {"factory_bootargs": factory, "bootcmd": bootcmd, "panel_bootargs": panel_bootargs(factory)}, indent=2))
    say("  Factory boot arguments saved to " + str(log_dir / "boot-environment.json"))

    say("\n[2/6] Service shell")
    enter_service_shell(c, factory)
    say("\n[3/6] Checking the panel")
    free = check_panel(c)
    existing = re.findall(r"^E:(\S+)$", c.shell(
        f'for p in {ROOT} {STAGE} /data/s1e; do if [ -e $p ] || [ -L $p ]; then echo "E:$p"; fi; done'), re.M)
    if "/data/s1e" in existing and c.value("readlink /data/s1e") != "s1e-panel/system/init.sh":
        raise InstallError("/data/s1e exists and is not S1E Panel's; nothing was changed")
    if ROOT in existing and args.check:
        say(f"  Note: {ROOT} exists from an earlier, unfinished installation (use --replace-incomplete)")
    elif ROOT in existing:
        if not args.replace_incomplete:
            raise InstallError(f"{ROOT} already exists from an earlier, unfinished installation. "
                               "Run again with --replace-incomplete to replace it.")
        c.shell(f"rm -rf {ROOT}.previous && mv {ROOT} {ROOT}.previous && sync", 60)
    if STAGE in existing and not args.check:
        c.shell(f"rm -rf {STAGE} && sync", 60)
    if free < 32 * 1024 + len(data) // 1024:
        raise InstallError(f"Not enough free space on /data ({free // 1024} MiB)")
    say(f"  Kernel, drivers, flash layout OK; {free // 1024} MiB free on /data")
    if args.check:
        say("\nCheck finished, nothing was written. Rebooting to the stock firmware.")
        c.s.write(b"reboot -f\r")
        return

    say("\n[4/6] Sending S1E Panel to the panel")
    fast = c.set_rate(921600) or c.set_rate(460800)
    say("  Console speed " + ("raised" if fast else "115200 baud (this takes about 15 minutes)"))
    c.run("mkdir -p /tmp/s1e-install")
    c.upload(data, "/tmp/s1e-install/bundle.tar.gz")
    c.reset_rate()
    say("  Unpacking and verifying the signed application...")
    c.shell(f"mkdir -m 700 {STAGE} && tar -xzf /tmp/s1e-install/bundle.tar.gz -C {STAGE} && rm /tmp/s1e-install/bundle.tar.gz", 120)
    result = c.shell(f"mkdir {STAGE}/releases && {STAGE}/system/update-check {STAGE}/initial.s1e "
                     f"{STAGE}/system/update-public.pem {STAGE}/releases/A", 180)
    if not re.search(r'^\{.*"files":', result, re.M):
        raise InstallError("The signed application did not verify:\n" + result[-500:])
    c.shell(f"rm {STAGE}/initial.s1e && mkdir -m 700 {STAGE}/data")
    if ssid:
        c.shell(f"mkdir -m 700 {STAGE}/data/wifi")
        c.write_secret(conf, f"{STAGE}/data/wifi/wpa.conf")
        conf = password = None
    state = json.dumps({"active": "A", "previous": "", "pending": "", "attempts": 0, "phase": "healthy", "staged": None},
                       separators=(",", ":"))
    c.shell(f"printf '%s\\n' '{state}' > {STAGE}/state.json && sync && mv {STAGE} {ROOT} && sync")
    c.shell("[ -L /data/s1e ] || ln -s s1e-panel/system/init.sh /data/s1e; sync")
    link = c.value("readlink /data/s1e")
    if link != "s1e-panel/system/init.sh":
        raise InstallError("Could not create the start entry /data/s1e")
    say(f"  Installed into {ROOT} (bundle SHA-256 {digest[:16]}...)")

    say("\n[5/6] Test start of S1E Panel (boot arguments not saved yet)")
    reboot_to_bootloader(c)
    if c.env("bootargs") != factory:
        raise InstallError("The boot arguments changed unexpectedly; nothing was saved")
    c.setenv("bootargs", panel_bootargs(factory))
    c.boot(SHELL_PROMPT, 90)
    ip = wait_healthy(c)
    say("  S1E Panel started and reports healthy" + (f" at {ip}" if ip else ""))

    say("\n[6/6] Saving the boot arguments")
    reboot_to_bootloader(c)
    if c.env("bootargs") != factory or c.env("bootcmd") != bootcmd:
        raise InstallError("The boot environment changed unexpectedly; nothing was saved")
    c.setenv("s1e_factory_bootargs", factory)
    c.setenv("bootargs", panel_bootargs(factory))
    c.setenv("bootdelay", "2")
    result = c.run("saveenv", UBOOT_PROMPT, 30)
    if "OK" not in result and "done" not in result.lower():
        raise InstallError("The bootloader did not confirm saveenv:\n" + result)
    c.boot(SHELL_PROMPT, 90)
    ip = wait_healthy(c)
    say("\nDone. S1E Panel now starts by itself.")
    if ip:
        say(f"Panel address: {ip}  ->  editor: https://{ip}:8443")
    else:
        say("Connect the panel to Wi-Fi on its screen: pull down from the top edge -> Settings -> Wi-Fi.")
    say("Next: docs/getting-started.md")


def restore(c, log_dir):
    say("Waiting for the bootloader. Power the panel on now.")
    c.bootloader()
    current, factory = c.env("bootargs") or "", c.env("s1e_factory_bootargs")
    if not factory:
        raise InstallError("No saved factory boot arguments on this panel (s1e_factory_bootargs). Nothing was changed.")
    (log_dir / "boot-environment-before-restore.json").write_text(json.dumps(
        {"bootargs": current, "s1e_factory_bootargs": factory}, indent=2))
    check_factory_bootargs(factory)
    c.setenv("bootargs", factory)
    result = c.run("saveenv", UBOOT_PROMPT, 30)
    if "OK" not in result and "done" not in result.lower():
        raise InstallError("The bootloader did not confirm saveenv:\n" + result)
    c.s.write(b"run bootcmd\r")
    say("Factory boot arguments restored; the stock firmware is starting. "
        "S1E Panel's files stay in /data/s1e-panel and are not used.")


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", required=True, help="serial port of the USB-UART adapter, e.g. COM5 or /dev/ttyUSB0")
    p.add_argument("--bundle", help="s1e-panel-first-install.tar.gz from the release")
    p.add_argument("--sums", help="SHA256SUMS.txt from the same release")
    p.add_argument("--wifi-ssid", help="connect to this Wi-Fi network on first start (password is asked)")
    p.add_argument("--check", action="store_true", help="only check the panel; nothing is written")
    p.add_argument("--replace-incomplete", action="store_true", help="replace files of an unfinished earlier run")
    p.add_argument("--restore-factory-boot", action="store_true", help="start the stock firmware again")
    p.add_argument("--log-dir", default="s1e-install-logs", help="where the console log and boot arguments go")
    a = p.parse_args()
    if not (a.restore_factory_boot or a.check or a.bundle):
        p.error("--bundle is required (or --check, --restore-factory-boot)")
    log_dir = pathlib.Path(a.log_dir) / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    c = Console(a.port, log_dir / "console.log")
    try:
        restore(c, log_dir) if a.restore_factory_boot else install(c, a, log_dir)
    except InstallError as e:
        say(f"\nStopped: {e}")
        say(f"Console log: {log_dir / 'console.log'}")
        return 1
    except KeyboardInterrupt:
        say("\nInterrupted. If the boot arguments were not saved yet, a power cycle starts the stock firmware.")
        return 1
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
