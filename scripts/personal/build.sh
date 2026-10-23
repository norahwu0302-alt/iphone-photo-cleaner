#!/bin/bash
# macOS + Xcode 26+ + XcodeGen only. No Apple account or signing secret is used.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="$root/build/personal"
mkdir -p "$out"
cd "$root"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build must run on macOS (use the Personal iPhone IPA GitHub workflow)." >&2
  exit 1
fi
for tool in xcodebuild xcrun xcodegen python3 ditto; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
xcodebuild -version | tee "$out/xcode-version.txt"
python3 - "$out/xcode-version.txt" <<'PY'
import re, sys
from pathlib import Path
version = re.search(r"Xcode (\d+)", Path(sys.argv[1]).read_text())
if not version or int(version.group(1)) < 26:
    raise SystemExit("Xcode 26+ is required by the FoundationModels import in this source.")
PY

python3 -m unittest discover -s scripts/personal -p 'test_*.py' -v
python3 scripts/personal/prepare.py
# prepare.py emits only numeric version fields read from the upstream spec.
source "$out/build.env"
export PERSONAL_SOURCE_ROOT="$root"
xcodegen generate --spec "$root/project.personal.yml" --project "$out"
project="$out/TidybytePersonal.xcodeproj"
scheme="TidybytePersonal"
signing=(CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY= CODE_SIGN_ENTITLEMENTS= DEVELOPMENT_TEAM=)

xcodebuild -showBuildSettings -json -project "$project" -scheme "$scheme" \
  -configuration Release -sdk iphoneos -destination 'generic/platform=iOS' \
  "${signing[@]}" > "$out/device-build-settings.json"
python3 - "$out/device-build-settings.json" <<'PY'
import json, sys
from pathlib import Path
targets = json.loads(Path(sys.argv[1]).read_text())
apps = [t["buildSettings"] for t in targets if t["target"] == "Tidybyte"]
if len(apps) != 1:
    raise SystemExit("Expected exactly one Tidybyte app target")
settings = apps[0]
expected = {"PRODUCT_BUNDLE_IDENTIFIER": "org.local.tidybyte.personal", "CODE_SIGNING_ALLOWED": "NO"}
for key, value in expected.items():
    if settings.get(key) != value:
        raise SystemExit(f"Unexpected {key}: {settings.get(key)!r}")
for key in ("CODE_SIGN_ENTITLEMENTS", "DEVELOPMENT_TEAM", "CODE_SIGN_IDENTITY"):
    if settings.get(key, ""):
        raise SystemExit(f"Personal build still has {key}")
if "PERSONAL_BUILD" not in settings.get("SWIFT_ACTIVE_COMPILATION_CONDITIONS", "").split():
    raise SystemExit("PERSONAL_BUILD conditional is missing")
PY

if [[ "${PERSONAL_RUN_TESTS:-1}" == "1" ]]; then
  xcrun simctl list devices available --json > "$out/simulators.json"
  simulator="$(python3 - "$out/simulators.json" <<'PY'
import json, re, sys
from pathlib import Path
candidates = []
for runtime, devices in json.loads(Path(sys.argv[1]).read_text())["devices"].items():
    match = re.search(r"iOS-(\d+)(?:-(\d+))?(?:-(\d+))?$", runtime)
    if not match:
        continue
    version = tuple(int(part or 0) for part in match.groups())
    if version[0] < 17:
        continue
    for device in devices:
        if device.get("isAvailable") and device["name"].startswith("iPhone"):
            candidates.append((version, device["name"], device["udid"]))
if not candidates:
    raise SystemExit("No available iPhone simulator with iOS 17+; install an iOS runtime.")
print(max(candidates)[2])
PY
)"
  xcodebuild test -project "$project" -scheme "$scheme" \
    -configuration Debug -sdk iphonesimulator \
    -destination "platform=iOS Simulator,id=$simulator" \
    -derivedDataPath "$out/SimulatorDerivedData" \
    -resultBundlePath "$out/PersonalTests-$(date -u +%Y%m%dT%H%M%SZ).xcresult" \
    -parallel-testing-enabled NO \
    -only-testing:TidybyteTests/AppLanguageTests \
    -only-testing:TidybyteTests/LanguagePreferenceStoreTests \
    -only-testing:TidybyteTests/WidgetHandoffTests \
    -only-testing:TidybyteTests/DuplicatesRegressionTests \
    -only-testing:TidybyteTests/CategorizationRegressionTests \
    "${signing[@]}" | tee "$out/tests.log"
fi

# This is a separate physical-device Release build, not the Simulator test app.
xcodebuild build -project "$project" -scheme "$scheme" \
  -configuration Release -sdk iphoneos -destination 'generic/platform=iOS' \
  -derivedDataPath "$out/DeviceDerivedData" ARCHS=arm64 ONLY_ACTIVE_ARCH=NO \
  "${signing[@]}" | tee "$out/build.log"
app="$out/DeviceDerivedData/Build/Products/Release-iphoneos/Tidybyte.app"
test -d "$app" || { echo "No physical-device app was produced" >&2; exit 1; }

stage="$(mktemp -d "$out/staging.XXXXXX")"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/Payload"
ditto "$app" "$stage/Payload/Tidybyte.app"
ipa="$out/TidyByte-Personal-unsigned.ipa"
# Remove only this known output file so a second build cannot retain stale ZIP entries.
rm -f "$ipa"
ditto -c -k --norsrc --noextattr --keepParent "$stage/Payload" "$ipa"
cp "$root/LICENSE" "$out/LICENSE"
python3 scripts/personal/verify_ipa.py "$ipa" | tee "$out/verification.log"
echo "Verified unsigned device IPA: $ipa"
echo "Sign and install it using Sideloadly on your own Windows computer."
