#!/usr/bin/env python3
"""Offline test of which input devices the relay takes (probe, is_candidate) and how it names
them (Node.id): USB and Bluetooth mice and keyboards, Steam Input's mouse (a Steam Controller's
trackpad, on the virtual bus), and not other virtual devices or the relay's own. The devices are
fakes (their ioctls answered here), so nothing is opened under /dev/input.

  input/test/probe-test.py [RELAY]   (default: input/input-relay.py next to this folder)
"""
import importlib.util
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
relay_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "input-relay.py")
relay = importlib.util.module_from_spec(importlib.util.spec_from_loader("relay", loader=None))
relay.__file__ = os.path.abspath(relay_path)
sys.path.insert(0, os.path.dirname(os.path.abspath(relay_path)))  # its game_pause and vrws
with open(relay_path) as f:
    exec(compile(f.read(), relay_path, "exec"), relay.__dict__)

failures = []


def check(label, got, want):
    ok = got == want
    print(("ok    " if ok else "FAIL  ") + label + ("" if ok else f": got {got!r}, want {want!r}"), flush=True)
    if not ok:
        failures.append(label)


USB, BT, VIRTUAL, HOST = relay.BUS_USB, relay.BUS_BLUETOOTH, relay.BUS_VIRTUAL, 0x19
STEAM_MOUSE = "Valve Software Steam Controller Puck Mouse"
MOUSE = {relay.EV_REL: {relay.REL_X, relay.REL_Y, relay.REL_WHEEL}, relay.EV_KEY: {relay.BTN_LEFT, relay.BTN_RIGHT}}
KEYBOARD = {relay.EV_KEY: {relay.KEY_A, 31, 32}}
VOLUME = {relay.EV_KEY: {relay.KEY_VOLUMEUP, relay.KEY_VOLUMEDOWN}}

# path: (name, bus, vendor, product, uniq, event bits)
DEVICES = {
    "/dev/input/event910": ("Logitech USB Mouse", USB, 0x046D, 0xC077, "", MOUSE),
    "/dev/input/event911": ("Keychron K2", BT, 0x05AC, 0x024F, "DC:2C:26:00:11:22", KEYBOARD),
    "/dev/input/event912": (STEAM_MOUSE, VIRTUAL, relay.VALVE, 0x1304, "", MOUSE),
    "/dev/input/event913": ("Steam virtual mouse", VIRTUAL, relay.VALVE, 0x1142, "", MOUSE),
    "/dev/input/event914": ("Valve Software Steam Controller Mouse", VIRTUAL, 0, 0, "", MOUSE),
    "/dev/input/event915": ("ydotoold virtual device", VIRTUAL, 0x2333, 0x6666, "", MOUSE),
    "/dev/input/event916": ("Valve Software Steam Controller Keyboard", VIRTUAL, relay.VALVE, 0x1304, "", KEYBOARD),
    "/dev/input/event917": (f"{relay.VIRTUAL_PREFIX} mouse", VIRTUAL, 0x4D44, 1, "", MOUSE),
    "/dev/input/event918": ("Valve Software Steam Controller Puck", VIRTUAL, relay.VALVE, 0x1304, "",
                            {relay.EV_KEY: {0x130, 0x131}}),
    "/dev/input/event919": ("gpio-keys", HOST, 0, 0, "", VOLUME),
}
FDS = {path: 900 + i for i, path in enumerate(DEVICES)}
BY_FD = {fd: DEVICES[path] for path, fd in FDS.items()}
CLOSED = []


def fake_open(path, flags):
    if path not in FDS:
        raise FileNotFoundError(path)
    return FDS[path]


def fake_ioctl(fd, request, buf):
    name, bus, vendor, product, uniq, _ = BY_FD[fd]
    if request == relay.EVIOCGID:
        buf[:] = struct.pack("HHHH", bus, vendor, product, 1)
    elif request == relay.eviocgname(len(buf)):
        buf[:len(name) + 1] = name.encode() + b"\0"
    elif request == relay.eviocguniq(len(buf)):
        buf[:len(uniq) + 1] = uniq.encode() + b"\0"
    else:
        raise OSError("unexpected ioctl")


fake_os = type(os)("os")
fake_os.__dict__.update(os.__dict__)
fake_os.open = fake_open
fake_os.close = CLOSED.append
relay.os = fake_os
relay.fcntl = type(os)("fcntl")
relay.fcntl.ioctl = fake_ioctl
relay.bits = lambda fd, ev, count: set(BY_FD[fd][5].get(ev, set()))


def probed(path):
    node = relay.probe(path)
    return None if node is None else (node.candidate, node.id)


check("a USB mouse", probed("/dev/input/event910"), (True, "usb:046d:c077:Logitech USB"))
check("a Bluetooth keyboard", probed("/dev/input/event911"), (True, "dc:2c:26:00:11:22"))
check("Steam Input's mouse (Valve, by vendor and name)", probed("/dev/input/event912"),
      (True, "steam:Valve Software Steam Controller Puck"))
check("Steam Input's mouse by vendor only", probed("/dev/input/event913"), (True, "steam:Steam virtual mouse"))
check("Steam Input's mouse by name only", probed("/dev/input/event914"),
      (True, "steam:Valve Software Steam Controller"))
check("another program's virtual mouse: not taken", probed("/dev/input/event915"), None)
check("Steam Input's keyboard: not taken", probed("/dev/input/event916"), None)
check("the relay's own virtual mouse: not taken", probed("/dev/input/event917"), None)
check("Steam's virtual gamepad: not taken", probed("/dev/input/event918"), None)
check("volume keys only: not a candidate", probed("/dev/input/event919"), (False, "usb:0000:0000:gpio-keys"))
check("refused nodes are closed", sorted(CLOSED), sorted(FDS[p] for p in (
    "/dev/input/event915", "/dev/input/event916", "/dev/input/event917", "/dev/input/event918")))

check("is_candidate: a USB mouse", relay.is_candidate("m", USB, 0x046D, True, False), True)
check("is_candidate: a USB device that's neither", relay.is_candidate("m", USB, 0x046D, False, False), False)
check("is_candidate: a Valve virtual mouse", relay.is_candidate("m", VIRTUAL, relay.VALVE, True, False), True)
check("is_candidate: a Valve mouse on the host bus", relay.is_candidate(STEAM_MOUSE, HOST, relay.VALVE, True, False),
      False)
check("the Steam mouse's id outlives its product", relay.Node("p", 0, STEAM_MOUSE, VIRTUAL, relay.VALVE, 0x1302, "",
                                                               True, False).id,
      relay.Node("p", 0, STEAM_MOUSE, VIRTUAL, relay.VALVE, 0x1304, "", True, False).id)
check("describe names the virtual bus",
      relay.Node("p", 0, STEAM_MOUSE, VIRTUAL, relay.VALVE, 0x1304, "", True, False).describe()["bus"], "virtual")

print("FAILED: " + ", ".join(failures) if failures else "all passed", flush=True)
sys.exit(1 if failures else 0)
