#!/usr/bin/env python3
"""Generate personal-build resources without editing upstream catalogs (stdlib)."""

import json
import re
import subprocess
from pathlib import Path


def version_setting(spec: str, key: str) -> str:
    values = re.findall(rf'^\s+{key}:\s*["\']?([0-9]+(?:\.[0-9]+)*)["\']?\s*$', spec, re.M)
    if len(values) != 1:
        raise ValueError(f"Expected exactly one numeric {key} in project.yml")
    return values[0]


def prepare(root: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    spec = (root / "project.yml").read_text(encoding="utf-8")
    version = version_setting(spec, "MARKETING_VERSION")
    build = version_setting(spec, "CURRENT_PROJECT_VERSION")
    (output / "build.env").write_text(
        f"export PERSONAL_MARKETING_VERSION={version}\nexport PERSONAL_BUILD_NUMBER={build}\n",
        encoding="utf-8",
    )
    catalog = json.loads((root / "Tidybyte/InfoPlist.xcstrings").read_text(encoding="utf-8"))
    display_name = catalog["strings"]["CFBundleDisplayName"]
    for localization in display_name["localizations"].values():
        localization["stringUnit"]["value"] = "TidyByte Test"
    display_name["comment"] = "Personal test build; kept distinct from the original app."
    resource_dir = output / "Resources"
    resource_dir.mkdir(exist_ok=True)
    (resource_dir / "InfoPlist.xcstrings").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    repository = Path(__file__).resolve().parents[2]
    out = repository / "build/personal"
    prepare(repository, out)
    source = {
        "upstream_repository": "https://github.com/360ghar/tidybyte",
        "upstream_base_commit": "ee61a5e14806cf79842492207b1cc71b95fb7c7e",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, text=True
        ).strip(),
        "working_tree_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=repository, text=True
        ).strip()),
        "version_source": "project.yml: MARKETING_VERSION and CURRENT_PROJECT_VERSION",
        "signing": "Unsigned; sign on your Windows computer before installing on iPhone.",
        "license": "MIT; original LICENSE is included in the app and download.",
    }
    (out / "SOURCE_INFO.json").write_text(json.dumps(source, indent=2) + "\n", encoding="utf-8")
