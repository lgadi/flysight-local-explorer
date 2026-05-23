from __future__ import annotations

import plistlib
import subprocess
from dataclasses import dataclass

from flask import abort

from . import config


@dataclass(frozen=True)
class Device:
    raw_node: str          # /dev/rdisk4s1 (the FAT partition, raw)
    block_node: str        # /dev/disk4s1
    whole_disk: str        # /dev/disk4 — for eject and disk-wide operations
    label: str
    size_bytes: int


def detect() -> Device | None:
    expected_label = config.get().device.label
    out = subprocess.check_output(
        ["diskutil", "list", "-plist", "external", "physical"],
        timeout=10,
    )
    plist = plistlib.loads(out)
    for disk in plist.get("AllDisksAndPartitions", []):
        whole_ident = disk.get("DeviceIdentifier", "")
        for part in disk.get("Partitions", []):
            if part.get("VolumeName") == expected_label:
                ident = part["DeviceIdentifier"]
                return Device(
                    raw_node=f"/dev/r{ident}",
                    block_node=f"/dev/{ident}",
                    whole_disk=f"/dev/{whole_ident}" if whole_ident else "",
                    label=part.get("VolumeName") or "",
                    size_bytes=int(part.get("Size") or 0),
                )
    return None


def detect_or_400() -> Device:
    dev = detect()
    if dev is None:
        label = config.get().device.label
        abort(400, description=f"No FlySight device detected (no external FAT partition labeled {label}).")
    return dev
