#!/usr/bin/env python3
"""Reject simulator, signed, or capability-bearing packages before publication."""

import argparse
import hashlib
import json
import plistlib
import struct
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


def check_macho(data: bytes) -> None:
    if len(data) < 32:
        raise ValueError("Executable has no complete Mach-O header")
    magic, cpu, _, file_type, commands, command_bytes, _, _ = struct.unpack_from("<8I", data)
    if magic != 0xFEEDFACF or cpu != 0x0100000C or file_type != 2:
        raise ValueError("Expected a thin arm64 Mach-O executable")
    end = 32 + command_bytes
    if end > len(data):
        raise ValueError("Truncated Mach-O load commands")
    offset = 32
    platforms = []
    for _ in range(commands):
        if offset + 8 > end:
            raise ValueError("Truncated Mach-O command")
        command, size = struct.unpack_from("<2I", data, offset)
        if size < 8 or offset + size > end:
            raise ValueError("Invalid Mach-O command size")
        if command == 0x1D:  # LC_CODE_SIGNATURE; no existing signing blob allowed.
            raise ValueError("Expected an unsigned executable, found a code signature")
        if command == 0x32:  # LC_BUILD_VERSION
            if size < 24:
                raise ValueError("Truncated LC_BUILD_VERSION")
            platforms.append(struct.unpack_from("<I", data, offset + 8)[0])
        offset += size
    if offset != end or platforms != [2]:  # PLATFORM_IOS=2, IOSSIMULATOR=7
        raise ValueError("Executable must target physical iOS (LC_BUILD_VERSION platform 2)")


def validate(ipa: Path, expected_license: bytes) -> dict:
    with zipfile.ZipFile(ipa) as package:
        entries = package.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entries are not allowed")
        apps = set()
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Unsafe ZIP member path")
            if len(path.parts) < 1 or path.parts[0] != "Payload":
                raise ValueError("IPA contains unexpected top-level content")
            if len(path.parts) >= 2 and path.parts[1].endswith(".app"):
                apps.add(path.parts[1])
            if any(part in {"PlugIns", "Watch", "_CodeSignature"} or part.endswith(".appex")
                   for part in path.parts):
                raise ValueError("Personal package must not contain extensions or signatures")
            if name.endswith((".entitlements", ".mobileprovision", ".xcent")):
                raise ValueError("Personal package must not carry entitlements or provisioning")
        if apps != {"Tidybyte.app"}:
            raise ValueError("Expected exactly Payload/Tidybyte.app")
        prefix = "Payload/Tidybyte.app/"
        info = plistlib.loads(package.read(prefix + "Info.plist"))
        if info.get("CFBundleSupportedPlatforms") != ["iPhoneOS"] or info.get("DTPlatformName") != "iphoneos":
            raise ValueError("Info.plist does not identify a physical iPhoneOS build")
        if info.get("CFBundleIdentifier") != "org.local.tidybyte.personal":
            raise ValueError("Unexpected bundle ID; upstream identity must not be reused")
        if info.get("CFBundleDisplayName") != "TidyByte Test":
            raise ValueError("Unexpected personal build display name")
        if info.get("MinimumOSVersion") != "17.0":
            raise ValueError("Expected the iOS 17.0 deployment target")
        if "NSExtension" in info:
            raise ValueError("App must not be an extension")
        executable = info.get("CFBundleExecutable", "")
        if not executable or PurePosixPath(executable).name != executable:
            raise ValueError("Invalid bundle executable")
        check_macho(package.read(prefix + executable))
        executable_mode = package.getinfo(prefix + executable).external_attr >> 16
        if not executable_mode & 0o111:
            raise ValueError("IPA lost the executable's Unix execute permission")
        if package.read(prefix + "LICENSE") != expected_license:
            raise ValueError("Original MIT license must be included without modification")
    return {
        "bundle_identifier": info["CFBundleIdentifier"],
        "display_name": info["CFBundleDisplayName"],
        "version": info["CFBundleShortVersionString"],
        "build_number": info["CFBundleVersion"],
        "minimum_ios": info["MinimumOSVersion"],
        "platform": "iPhoneOS arm64 (not Simulator)",
        "ipa_sha256": hashlib.sha256(ipa.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipa", type=Path)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    result = validate(args.ipa, (repository / "LICENSE").read_bytes())
    result.update(json.loads((args.ipa.parent / "SOURCE_INFO.json").read_text(encoding="utf-8")))
    result["built_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["xcode"] = (args.ipa.parent / "xcode-version.txt").read_text(encoding="utf-8").strip()
    args.ipa.with_suffix(".ipa.sha256").write_text(
        result["ipa_sha256"] + "  " + args.ipa.name + "\n", encoding="utf-8"
    )
    (args.ipa.parent / "BUILD_INFO.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
