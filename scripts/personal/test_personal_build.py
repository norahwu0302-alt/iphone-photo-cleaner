"""Portable checks for the install-package guardrails; no iOS SDK required."""

import json
import plistlib
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from prepare import prepare, version_setting
from verify_ipa import check_macho, validate


def macho(platform=2, cpu=0x0100000C, signed=False):
    command = struct.pack("<6I", 0x32, 24, platform, 0x00110000, 0x001A0000, 0)
    if signed:
        command += struct.pack("<4I", 0x1D, 16, 0, 0)
    return struct.pack("<8I", 0xFEEDFACF, cpu, 0, 2, 2 if signed else 1, len(command), 0, 0) + command


class PackageValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ipa = Path(self.temp.name) / "test.ipa"
        self.license = b"MIT License\nCopyright (c) 2026 Saksham Mittal\n"
        self.info = {
            "CFBundleSupportedPlatforms": ["iPhoneOS"],
            "DTPlatformName": "iphoneos",
            "CFBundleIdentifier": "org.local.tidybyte.personal",
            "CFBundleDisplayName": "TidyByte Test",
            "CFBundleExecutable": "Tidybyte",
            "CFBundleShortVersionString": "1.1.1",
            "CFBundleVersion": "8",
            "MinimumOSVersion": "17.0",
        }

    def write(self, executable=None, extra=None, mode=0o100755):
        prefix = "Payload/Tidybyte.app/"
        with zipfile.ZipFile(self.ipa, "w") as package:
            package.writestr(prefix + "Info.plist", plistlib.dumps(self.info))
            package.writestr(prefix + "LICENSE", self.license)
            entry = zipfile.ZipInfo(prefix + "Tidybyte")
            entry.create_system = 3
            entry.external_attr = mode << 16
            package.writestr(entry, executable if executable is not None else macho())
            for name, data in (extra or {}).items():
                package.writestr(prefix + name, data)

    def test_valid_unsigned_device_package(self):
        self.write()
        result = validate(self.ipa, self.license)
        self.assertEqual(result["platform"], "iPhoneOS arm64 (not Simulator)")
        self.assertEqual(result["version"], "1.1.1")
        self.assertEqual(len(result["ipa_sha256"]), 64)

    def test_arm64_simulator_is_rejected_even_with_device_info_plist(self):
        self.write(executable=macho(platform=7))
        with self.assertRaisesRegex(ValueError, "physical iOS"):
            validate(self.ipa, self.license)

    def test_simulator_info_plist_is_rejected(self):
        self.info["DTPlatformName"] = "iphonesimulator"
        self.write()
        with self.assertRaisesRegex(ValueError, "physical iPhoneOS"):
            validate(self.ipa, self.license)

    def test_original_author_bundle_id_is_rejected(self):
        self.info["CFBundleIdentifier"] = "com.sakshammittal.tidybyte"
        self.write()
        with self.assertRaisesRegex(ValueError, "bundle ID"):
            validate(self.ipa, self.license)

    def test_widget_provisioning_entitlements_and_signature_are_rejected(self):
        for name in ("PlugIns/Widget.appex/Info.plist", "embedded.mobileprovision", "app.entitlements", "_CodeSignature/CodeResources"):
            with self.subTest(name=name):
                self.write(extra={name: b"unexpected"})
                with self.assertRaises(ValueError):
                    validate(self.ipa, self.license)

    def test_executable_signature_is_rejected(self):
        self.write(executable=macho(signed=True))
        with self.assertRaisesRegex(ValueError, "code signature"):
            validate(self.ipa, self.license)

    def test_zip_must_preserve_execute_permissions(self):
        self.write(mode=0o100644)
        with self.assertRaisesRegex(ValueError, "execute permission"):
            validate(self.ipa, self.license)

    def test_original_license_is_required(self):
        self.write()
        with self.assertRaisesRegex(ValueError, "MIT license"):
            validate(self.ipa, b"another license")

    def test_truncated_and_non_arm64_executables_are_rejected(self):
        for data in (b"", macho()[:-1], macho(cpu=0x01000007)):
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    check_macho(data)


class PrepareTests(unittest.TestCase):
    def test_catalog_changes_only_the_display_name_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Tidybyte").mkdir()
            (root / "project.yml").write_text(
                'settings:\n  MARKETING_VERSION: "1.1.1"\n  CURRENT_PROJECT_VERSION: 8\n', encoding="utf-8"
            )
            catalog = {"sourceLanguage": "en", "strings": {
                "CFBundleDisplayName": {"localizations": {
                    "en": {"stringUnit": {"value": "TidyByte"}},
                    "zh-Hans": {"stringUnit": {"value": "TidyByte"}},
                }},
                "NSPhotoLibraryUsageDescription": {"localizations": {
                    "zh-Hans": {"stringUnit": {"value": "允许读取照片"}},
                }},
            }}
            source = root / "Tidybyte/InfoPlist.xcstrings"
            source.write_text(json.dumps(catalog), encoding="utf-8")
            original = source.read_bytes()
            output = root / "build/personal"
            prepare(root, output)
            generated = json.loads((output / "Resources/InfoPlist.xcstrings").read_text(encoding="utf-8"))
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(generated["strings"]["NSPhotoLibraryUsageDescription"], catalog["strings"]["NSPhotoLibraryUsageDescription"])
            for value in generated["strings"]["CFBundleDisplayName"]["localizations"].values():
                self.assertEqual(value["stringUnit"]["value"], "TidyByte Test")
            self.assertIn("PERSONAL_BUILD_NUMBER=8", (output / "build.env").read_text())

    def test_version_parser_rejects_ambiguous_or_shell_values(self):
        for source in ("  MARKETING_VERSION: 1\n  MARKETING_VERSION: 2\n", '  MARKETING_VERSION: "$(unsafe)"\n'):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    version_setting(source, "MARKETING_VERSION")


if __name__ == "__main__":
    unittest.main()
