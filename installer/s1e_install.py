"""First installation of S1E Panel on an Aqara S1E (NPD1121WSK01) over the service console (UART).

    python s1e_install.py --port COM5 --check
    python s1e_install.py --port COM5 --bundle s1e-panel-first-install.tar.gz --sums SHA256SUMS.txt
    python s1e_install.py --port COM5 --restore-factory-boot

What it does, in order (see docs/installation.md):
 1. Waits for the panel's bootloader (U-Boot), stops it and saves the factory boot settings to --log-dir.
 2. Boots the stock kernel once into a service shell (temporary arguments, nothing saved).
 3. Checks the hardware and the existing data volume. --check stops here and reboots to the stock firmware.
 4. Sends the first-install bundle over the console, verifies its SHA-256, unpacks it into a new folder
    /data/s1e-panel, verifies the signed application and creates the panel's identity and HTTPS certificate.
 5. Replaces the Aqara start-up picture with the S1E Panel logo (boot-logo.jpg next to this script),
    keeping the original on the panel and on this computer. --keep-boot-logo skips this.
 6. Boots S1E Panel once with the new boot arguments, still without saving them, and waits until the
    interface reports healthy.
 7. Only then saves the boot settings (the factory values are kept as s1e_factory_bootargs and
    s1e_factory_bootdelay) and starts the panel.

The factory root file system, kernel, partitions and bootloader stay untouched. Until step 7 a power cycle
returns the panel to the stock firmware (with the new start-up picture, if step 5 ran).
--restore-factory-boot puts the factory boot settings and the original start-up picture back.

Needs Python 3.9+ and pyserial (pip install pyserial). The Wi-Fi password is never written to the log.
"""
import argparse
import base64
import datetime
import getpass
import gzip
import hashlib
import json
import pathlib
import re
import sys
import tarfile
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("pyserial is missing: run  python -m pip install pyserial")

UBOOT_PROMPT, SHELL_PROMPT = b"SigmaStar # ", b"/ # "
# Partition layout of the NPD1121WSK01 board; the data volume (UBI) is mtd13, the start-up picture is on MISC (mtd10).
PARTITIONS = ["BOOT0", "BOOT1", "ENV", "ENV1", "KEY_CUST", "KERNEL", "KERNEL_BAK", "rootfs", "rootfs_bak",
              "factory", "MISC", "RES", "RES_BAK", "UBI"]
# The data volume by number (ubi0_0): its name differs between panels, and a name that does not match
# would send the panel to the stock init with the volume already attached.
BOOTSTRAP = "mount -a;mount -t ubifs ubi0_0 /data;sh /data/s1e;exec /linuxrc"
BUNDLE_FILES = {"initial.s1e", "system/panel-update", "system/update-check", "system/update-public.pem",
                "system/init.sh", "system/app.sh", "system/network.sh", "system/dhcp.sh", "system/init-hardware.sh"}
MODULES = ["lcd_drv", "mhal", "mi_common", "mi_sys", "mi_gfx", "mi_disp", "mi_panel", "mi_fb", "bl_fdrv"]
UBOOT_LINE_LIMIT = 511          # the vendor U-Boot reads at most this many characters per command
CHUNK = 768                     # base64 characters per console line; the shell's line editor holds about 1 KiB
ROOT, STAGE = "/data/s1e-panel", "/data/s1e-panel.installing"
MISC = "/tmp/s1e-misc"
FWFS = ("/bin/fwfs --block_size=131072 --subblock_size=32768 --block_cycles=500 --read_size=2048 --prog_size=2048 "
        "--cache_size=32768 --file_cache_size=32768 --cache_pool_size=2 --block_count=8 --lookahead_size=8")
LOGO, LOGO_BACKUP = "aqara.jpg", "aqara.jpg.s1e-original"


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


def check_logo(path):
    data = path.read_bytes()
    if not data.startswith(b"\xff\xd8") or len(data) > 256 * 1024:
        raise InstallError(f"{path.name} is not a JPEG picture of a usable size")
    return data


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
        try:
            self.s.close()
        finally:
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
        line = command.encode("ascii") + b"\r"
        if prompt == UBOOT_PROMPT:
            # U-Boot reads the console without a buffer: send in small pieces so no character is dropped
            for i in range(0, len(line), 16):
                self.s.write(line[i:i + 16])
                self.s.flush()
                time.sleep(0.003)
        else:
            self.s.write(line)
            self.s.flush()
        return self.until(prompt, timeout)

    def uboot(self, command, timeout=15):
        """A bootloader command that is safe to repeat (printenv, setenv, saveenv): a line garbled on the way
        is cleared with Ctrl+C and sent again."""
        for attempt in range(3):
            try:
                return self.run(command, UBOOT_PROMPT, timeout)
            except InstallError:
                if attempt == 2:
                    raise
                self.s.write(b"\x03\r")
                self.s.flush()
                try:
                    self.until(UBOOT_PROMPT, 5)
                except InstallError:
                    pass

    def read_all(self):
        while self.read():
            pass

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
        """Wait for U-Boot after the panel is powered or rebooted and stop it with Enter.

        Everything received counts from the first byte: a reboot can print the U-Boot banner at once."""
        self.s.write(b"\r")
        out, state, last, end = bytearray(), "wait", 0.0, time.monotonic() + minutes * 60
        hinted = False
        while time.monotonic() < end:
            out.extend(self.read())
            tail = bytes(out[-20000:]).replace(b"\r", b"")
            if tail.endswith(UBOOT_PROMPT):
                # The Enter presses still on their way give a few more prompts: let them arrive, then start clean
                time.sleep(0.5)
                self.read_all()
                self.uboot("")
                return tail.decode("utf-8", "replace")
            if state == "wait" and b"U-Boot" in tail:
                state = "stop"
            elif state == "wait" and any(mark in tail for mark in (b"Starting kernel", b"check mount")):
                # Switched on before this program was listening: the bootloader's moment has passed.
                # (A running stock system repeats only its login prompt, which is not a sign of a start.)
                if not hinted:
                    say("  The panel is already starting up (its bootloader came before this program was listening). "
                        "Switch the panel's power off, wait 3 seconds and switch it on again now.")
                    hinted = True
                out = bytearray()
            if state == "stop":
                if b"Starting kernel" in tail or b"NAND read:" in tail:
                    say("  The bootloader was not stopped in time. Switch the panel's power off and on again, "
                        "keeping the USB-UART adapter connected (see the guide for panels made after July 2023).")
                    out, state = bytearray(), "wait"
                elif time.monotonic() - last >= 0.01:
                    self.s.write(b"\r")
                    last = time.monotonic()
        raise InstallError("No bootloader on the console. Check the wiring (TX->RX, RX->TX, GND) and the port.")

    def env(self, name):
        text = self.uboot("printenv " + name).replace("\r", "")
        m = re.search(r"^" + re.escape(name) + r"=(.*)$", text, re.M)
        return m.group(1) if m else None

    def setenv(self, name, value):
        """Set a variable; None removes it."""
        if value is None:
            command = f"setenv {name}"
        else:
            if "'" in value:
                raise InstallError("Unexpected quote in " + name)
            command = f"setenv {name} '{value}'"
        for _ in range(3):          # a value garbled on the way shows up in the check and is set again
            self.uboot(command)
            if self.env(name) == value:
                return
        raise InstallError(f"The bootloader did not accept {name}. Nothing was saved.")

    def saveenv(self):
        result = self.uboot("saveenv", 30)
        if "OK" not in result and "done" not in result.lower():
            raise InstallError("The bootloader did not confirm saveenv:\n" + result)

    def boot(self, prompt=SHELL_PROMPT, timeout=60):
        return self.run("run bootcmd", prompt, timeout)

    def upload(self, data, destination, progress=True):
        """Send a file in base64 lines and check its SHA-256 on the panel."""
        encoded = base64.b64encode(data).decode("ascii")
        self.run(f": > {destination}.b64")
        self.run("stty -F /dev/ttyS0 -echo")
        self.quiet = True
        started, total = time.monotonic(), len(encoded)
        try:
            for offset in range(0, total, CHUNK):
                self.run(f"printf '%s' '{encoded[offset:offset + CHUNK]}' >> {destination}.b64", timeout=10)
                if progress and offset // CHUNK % 100 == 0:
                    done = offset / total
                    left = (time.monotonic() - started) / done * (1 - done) if done else 0
                    print(f"\r  {done * 100:5.1f} %  about {left / 60:.0f} min left   ", end="", flush=True)
        finally:
            self.quiet = False
            self.run("stty -F /dev/ttyS0 echo")
        if progress:
            say("\r  100.0 %                          ")
        self.run(f"base64 -d {destination}.b64 > {destination} && rm {destination}.b64", timeout=60)
        if hashlib.sha256(data).hexdigest() not in self.shell(f"sha256sum {destination}"):
            raise InstallError(f"{destination} arrived damaged. Run the installer again.")

    def download(self, path, timeout=60):
        """A small file from the panel, through gzip and base64."""
        self.quiet = True
        try:
            text = self.run(f"printf '\\nS1E_BEGIN\\n'; gzip -c {path} | base64; printf '\\nS1E_END\\n'", SHELL_PROMPT, timeout)
        finally:
            self.quiet = False
        m = re.search(r"^S1E_BEGIN\n([A-Za-z0-9+/=\n]+)\nS1E_END$", text, re.M)
        if not m:
            raise InstallError(f"Could not read {path} from the panel")
        return gzip.decompress(base64.b64decode(m.group(1)))

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
    # BusyBox prints "uid=0(root) ..." or, without a user database, "uid=0 gid=0(root)"
    if not re.search(r"^uid=0(?:\(|\s|$)", c.shell("id"), re.M):
        raise InstallError("No root shell")
    c.run("[ -r /proc/mtd ] || mount -t proc proc /proc")
    c.run("[ -d /sys/class/mtd ] || mount -t sysfs sysfs /sys")
    if " /tmp tmpfs " not in c.shell("cat /proc/mounts"):
        c.run("mount -t tmpfs -o size=24m tmpfs /tmp")


def check_panel(c, writable):
    """Checks of the running stock system and the data volume (mounted read-only unless writable).
    Returns free space on the data volume in KiB."""
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
    options = "" if writable else "-o ro "
    if not re.search(r"^\S+ /data ubifs ", c.shell("cat /proc/mounts"), re.M):
        if not c.has_line(f"ubiattach /dev/ubi_ctrl -m 13 -d 1 && mount -t ubifs {options}ubi1_0 /data && echo DATA_READY",
                          "DATA_READY", 30):
            raise InstallError("The data volume did not mount")
    elif writable:
        c.run("mount -o remount,rw /data")
    return check_panel_free(c)


def check_panel_free(c):
    m = re.search(r"\s(\d+)\s+(\d+)\s+(\d+)\s+\d+%\s+/data$", c.shell("df -k /data"), re.M)
    if not m:
        raise InstallError("Could not read free space on /data")
    return int(m.group(3))


def create_identity(c, base):
    """Start the panel's core once, offline, so it creates its identity and HTTPS certificate.

    The updater serves its recovery HTTPS with this certificate; on a fresh installation it must exist before
    the first start."""
    run = "/tmp/s1e-install/run"
    c.shell(f"mkdir -p {run} && ({base}/releases/A/bin/panel-core --data {base}/data --run {run} "
            f"--web {base}/releases/A/web > /tmp/s1e-install/core.log 2>&1 & echo $! > /tmp/s1e-install/core.pid)")
    try:
        for _ in range(30):
            if c.has_line(f"[ -s {base}/data/tls/cert.pem ] && [ -s {base}/data/tls/key.pem ] && echo FOUND", "FOUND"):
                return
            time.sleep(2)
        raise InstallError("The panel did not create its certificate:\n" + c.shell("tail -n 20 /tmp/s1e-install/core.log"))
    finally:
        c.shell("kill $(cat /tmp/s1e-install/core.pid) 2>/dev/null; sleep 1; "
                "kill -9 $(cat /tmp/s1e-install/core.pid) 2>/dev/null; sync")


def misc_mount(c, writable):
    c.run(f"umount {MISC} 2>/dev/null; mkdir -p {MISC}")
    c.run(f"{FWFS} {'' if writable else '-o ro '}/dev/mtd10 {MISC}", timeout=30)
    if f"fwfs {MISC} fuse.fwfs {'rw' if writable else 'ro'}," not in c.shell("cat /proc/mounts"):
        raise InstallError("The start-up picture partition (MISC) did not mount")


def misc_hashes(c):
    text = c.shell(f"(cd {MISC} && sha256sum *)", 30)
    return dict((name, sha) for sha, name in re.findall(r"^([a-f0-9]{64})  ([A-Za-z0-9_.-]+)$", text, re.M))


def replace_logo(c, logo, log_dir):
    """Put the S1E Panel logo in place of the Aqara start-up picture; the original stays next to it."""
    digest = hashlib.sha256(logo).hexdigest()
    misc_mount(c, False)
    try:
        before = misc_hashes(c)
        if LOGO not in before or "config.ini" not in before:
            raise InstallError("Unexpected files in the start-up picture partition; it was not changed")
        if before[LOGO] == digest:
            say("  The start-up picture is already the S1E Panel logo")
            return
        original = c.download(f"{MISC}/{LOGO}")
        if hashlib.sha256(original).hexdigest() != before[LOGO]:
            raise InstallError("Could not back up the original start-up picture; it was not changed")
        (log_dir / "aqara-original.jpg").write_bytes(original)
        c.upload(logo, "/tmp/s1e-install/logo.jpg", progress=False)
        misc_mount(c, True)
        keep = "" if LOGO_BACKUP in before else f"cp {MISC}/{LOGO} {MISC}/{LOGO_BACKUP} && "
        c.shell(f"{keep}cp /tmp/s1e-install/logo.jpg {MISC}/{LOGO}.s1e-new && sync", 30)
        staged = misc_hashes(c)
        if staged.get(f"{LOGO}.s1e-new") != digest or staged.get(LOGO_BACKUP, before.get(LOGO_BACKUP)) is None:
            raise InstallError("Staging the new start-up picture failed; the original is unchanged")
        c.shell(f"mv {MISC}/{LOGO}.s1e-new {MISC}/{LOGO} && sync", 30)
        misc_mount(c, False)
        expected = dict(before, **{LOGO: digest, LOGO_BACKUP: before.get(LOGO_BACKUP, before[LOGO])})
        if misc_hashes(c) != expected:
            raise InstallError("The start-up picture partition does not read back as written")
        say("  Start-up picture replaced; the original is kept on the panel and in " + str(log_dir / "aqara-original.jpg"))
    finally:
        c.run(f"cd /; umount {MISC} 2>/dev/null; sync")


def restore_logo(c):
    misc_mount(c, False)
    try:
        before = misc_hashes(c)
        if LOGO_BACKUP not in before:
            say("  The start-up picture was not replaced; nothing to restore")
            return
        misc_mount(c, True)
        c.shell(f"cp {MISC}/{LOGO_BACKUP} {MISC}/{LOGO}.s1e-new && sync && mv {MISC}/{LOGO}.s1e-new {MISC}/{LOGO} && "
                f"rm {MISC}/{LOGO_BACKUP} && sync", 30)
        misc_mount(c, False)
        after = misc_hashes(c)
        if after.get(LOGO) != before[LOGO_BACKUP] or LOGO_BACKUP in after:
            raise InstallError("The original start-up picture did not read back")
        say("  Original Aqara start-up picture restored")
    finally:
        c.run(f"cd /; umount {MISC} 2>/dev/null; sync")


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
                        for _ in range(10):         # Wi-Fi may still be waiting for its DHCP address
                            ip = c.value("cat /tmp/s1e-panel/run/ip 2>/dev/null")
                            if ip:
                                return ip
                            time.sleep(3)
                        return ""
                except ValueError:
                    pass
    raise InstallError("S1E Panel did not report a healthy start. Nothing was saved: switch the panel's power off "
                       "and on to return to the stock firmware.")


def reboot_to_bootloader(c):
    c.run("sync")
    c.s.write(b"reboot -f\r")
    c.s.flush()
    return c.bootloader(2)


def install(c, args, log_dir):
    data, digest = check_bundle(pathlib.Path(args.bundle), args.sums) if args.bundle else (b"", "")
    logo = None
    if not args.check and not args.keep_boot_logo:
        path = pathlib.Path(args.boot_logo)
        if not path.is_file():
            raise InstallError(f"{path} not found. Download boot-logo.jpg from the release next to this script, "
                               "or run with --keep-boot-logo to keep the Aqara start-up picture.")
        logo = check_logo(path)
    ssid = password = None
    if args.wifi_ssid and not args.check:
        if args.wifi_password_file:
            password = pathlib.Path(args.wifi_password_file).read_text(encoding="utf-8").strip("\r\n")
        else:
            password = getpass.getpass(f"Password for Wi-Fi '{args.wifi_ssid}': ")
        ssid = args.wifi_ssid
        conf = wpa_conf(ssid, password)
    if args.bundle:
        say(f"Bundle {pathlib.Path(args.bundle).name}: {len(data) / 1048576:.1f} MiB, SHA-256 OK")

    say("\n[1/7] Waiting for the bootloader. Switch the panel's power on now "
        "(keep the USB-UART adapter plugged into the computer).")
    c.bootloader()
    factory = c.env("bootargs") or ""
    bootcmd = c.env("bootcmd") or ""
    bootdelay = c.env("bootdelay")
    check_factory_bootargs(factory)
    (log_dir / "boot-environment.json").write_text(json.dumps(
        {"factory_bootargs": factory, "bootcmd": bootcmd, "bootdelay": bootdelay,
         "panel_bootargs": panel_bootargs(factory)}, indent=2))
    say("  Factory boot settings saved to " + str(log_dir / "boot-environment.json"))

    say("\n[2/7] Service shell")
    enter_service_shell(c, factory)
    say("\n[3/7] Checking the panel")
    free = check_panel(c, writable=not args.check)
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
        say(f"  Removing the earlier installation in {ROOT}")
        c.shell(f"rm -rf {ROOT} {ROOT}.previous && sync", 120)
    if STAGE in existing and not args.check:
        c.shell(f"rm -rf {STAGE} && sync", 60)
    if not args.check and (ROOT in existing or STAGE in existing):
        free = check_panel_free(c)
    if free < 32 * 1024 + len(data) // 1024:
        raise InstallError(f"Not enough free space on /data ({free // 1024} MiB)")
    say(f"  Kernel, drivers, flash layout OK; {free // 1024} MiB free on /data")
    if not c.has_line("[ -x /bin/fwfs ] && [ -c /dev/mtd10 ] && echo FOUND", "FOUND"):
        if logo is not None:
            raise InstallError("The start-up picture cannot be changed on this panel (no /bin/fwfs). "
                               "Nothing was installed; run again with --keep-boot-logo.")
        say("  Note: the start-up picture cannot be changed on this panel (no /bin/fwfs); use --keep-boot-logo")
    if args.check:
        say("\nCheck finished: nothing was installed and the boot settings were not changed. "
            "Rebooting to the stock firmware.")
        c.s.write(b"umount /data; reboot -f\r")
        return

    say("\n[4/7] Sending S1E Panel to the panel (115200 baud: about 25-30 minutes; keep the wires still)")
    c.run("mkdir -p /tmp/s1e-install")
    c.upload(data, "/tmp/s1e-install/bundle.tar.gz")
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
    say("  Creating the panel's identity and HTTPS certificate...")
    create_identity(c, STAGE)
    state = json.dumps({"active": "A", "previous": "", "pending": "", "attempts": 0, "phase": "healthy", "staged": None},
                       separators=(",", ":"))
    c.shell(f"printf '%s\\n' '{state}' > {STAGE}/state.json && sync && mv {STAGE} {ROOT} && sync")
    c.shell("[ -L /data/s1e ] || ln -s s1e-panel/system/init.sh /data/s1e; sync")
    if c.value("readlink /data/s1e") != "s1e-panel/system/init.sh":
        raise InstallError("Could not create the start entry /data/s1e")
    c.run("umount /data; sync")
    say(f"  Installed into {ROOT} (bundle SHA-256 {digest[:16]}...)")

    say("\n[5/7] Start-up picture")
    if logo is None:
        say("  Kept the Aqara start-up picture (--keep-boot-logo)")
    else:
        replace_logo(c, logo, log_dir)

    say("\n[6/7] Test start of S1E Panel (boot settings not saved yet)")
    reboot_to_bootloader(c)
    if c.env("bootargs") != factory:
        raise InstallError("The boot arguments changed unexpectedly; nothing was saved")
    c.setenv("bootargs", panel_bootargs(factory))
    c.boot(SHELL_PROMPT, 90)
    ip = wait_healthy(c)
    say("  S1E Panel started and reports healthy" + (f" at {ip}" if ip else ""))

    say("\n[7/7] Saving the boot settings")
    reboot_to_bootloader(c)
    if c.env("bootargs") != factory or c.env("bootcmd") != bootcmd or c.env("bootdelay") != bootdelay:
        raise InstallError("The boot environment changed unexpectedly; nothing was saved")
    c.setenv("s1e_factory_bootargs", factory)
    c.setenv("s1e_factory_bootdelay", "unset" if bootdelay is None else bootdelay)
    c.setenv("bootargs", panel_bootargs(factory))
    c.setenv("bootdelay", "2")
    c.saveenv()
    c.boot(SHELL_PROMPT, 90)
    ip = wait_healthy(c)
    say("\nDone. S1E Panel now starts by itself.")
    if ip:
        say(f"Panel address: {ip}  ->  editor: https://{ip}:8443")
    else:
        say("Connect the panel to Wi-Fi on its screen: pull down from the top edge -> Settings -> Wi-Fi.")
    say("Next: https://github.com/alexshemr/s1e-panel/blob/main/docs/getting-started.md")


def restore(c, log_dir):
    say("Waiting for the bootloader. Switch the panel's power on now (keep the USB-UART adapter connected).")
    c.bootloader()
    current, factory = c.env("bootargs") or "", c.env("s1e_factory_bootargs")
    if not factory:
        raise InstallError("No saved factory boot arguments on this panel (s1e_factory_bootargs). Nothing was changed.")
    delay = c.env("s1e_factory_bootdelay")
    (log_dir / "boot-environment-before-restore.json").write_text(json.dumps(
        {"bootargs": current, "bootdelay": c.env("bootdelay"), "s1e_factory_bootargs": factory,
         "s1e_factory_bootdelay": delay}, indent=2))
    check_factory_bootargs(factory)
    c.setenv("bootargs", factory)
    if delay is not None:
        c.setenv("bootdelay", None if delay == "unset" else delay)
    c.setenv("s1e_factory_bootargs", None)
    c.setenv("s1e_factory_bootdelay", None)
    c.saveenv()
    say("  Factory boot settings restored")
    # The start-up picture: once more through the service shell (temporary arguments, not saved)
    enter_service_shell(c, factory)
    restore_logo(c)
    c.s.write(b"reboot -f\r")
    say("Done: the stock firmware is starting. S1E Panel's files stay in /data/s1e-panel and are not used.")


def ports():
    found = [p.device for p in serial.tools.list_ports.comports()]
    return ", ".join(found) if found else "none found"


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--port", required=True, help="serial port of the USB-UART adapter, e.g. COM5 or /dev/ttyUSB0")
    p.add_argument("--bundle", help="s1e-panel-first-install.tar.gz from the release")
    p.add_argument("--sums", help="SHA256SUMS.txt from the same release")
    p.add_argument("--wifi-ssid", help="connect to this Wi-Fi network on first start (password is asked)")
    p.add_argument("--wifi-password-file", help="read the Wi-Fi password from this file instead of asking")
    p.add_argument("--boot-logo", default=str(pathlib.Path(__file__).with_name("boot-logo.jpg")),
                   help="start-up picture instead of the Aqara one (default: boot-logo.jpg next to this script)")
    p.add_argument("--keep-boot-logo", action="store_true", help="keep the Aqara start-up picture")
    p.add_argument("--check", action="store_true", help="only check the panel; nothing is installed")
    p.add_argument("--replace-incomplete", action="store_true", help="remove the files of an earlier installation (its settings too) and install again")
    p.add_argument("--restore-factory-boot", action="store_true",
                   help="start the stock firmware again and put the Aqara start-up picture back")
    p.add_argument("--log-dir", default="s1e-install-logs", help="where the console log and boot settings go")
    a = p.parse_args()
    if not (a.restore_factory_boot or a.check or a.bundle):
        p.error("--bundle is required (or --check, --restore-factory-boot)")
    log_dir = pathlib.Path(a.log_dir) / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        c = Console(a.port, log_dir / "console.log")
    except (serial.SerialException, OSError) as e:
        say(f"Cannot open {a.port}: {e}\nSerial ports on this computer: {ports()}. "
            "Close other programs that use the port (terminals, other installers).")
        return 1
    try:
        restore(c, log_dir) if a.restore_factory_boot else install(c, a, log_dir)
    except InstallError as e:
        say(f"\nStopped: {e}")
        say(f"Console log: {log_dir / 'console.log'}")
        return 1
    except (serial.SerialException, OSError) as e:
        say(f"\nStopped: lost the connection to the USB-UART adapter on {a.port} ({e}).\n"
            "Keep the adapter plugged into the computer and switch only the panel's power. If the adapter powers "
            "the panel too, its port disappears on every power cycle: power the panel separately.\n"
            f"Serial ports now: {ports()}. Run the installer again; if it stopped after [4/7], add --replace-incomplete.\n"
            f"Console log: {log_dir / 'console.log'}")
        return 1
    except KeyboardInterrupt:
        say("\nInterrupted. If the boot settings were not saved yet, a power cycle starts the stock firmware.")
        return 1
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
