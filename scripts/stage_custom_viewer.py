"""Copy a Windows MCP development build into a NEW portable directory.

Uses Firestorm's own file manifest with packaging content enabled, but only the
copy action: no NSIS, URL registration, updater installation or signing step.
Run with the viewer build's Python environment after compilation succeeds.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    checkout = args.checkout.resolve(strict=True)
    destination = args.destination.resolve()
    if destination.exists():
        raise ValueError("Destination must be new; never overwrite an installed or previous viewer")
    if destination == checkout or checkout in destination.parents:
        raise ValueError("Portable destination must be outside the source checkout")
    source = checkout / "indra/newview"
    build = checkout / "build-vc170-64/newview"
    cache = (build.parent / "CMakeCache.txt").read_text()
    def setting(key):
        match = re.search(r"^" + re.escape(key) + r":[^=]+=(.*)$", cache, re.M)
        if match is None:
            raise ValueError(f"Build configuration lacks {key}")
        return match.group(1).strip()
    channel = setting("VIEWER_CHANNEL")
    profiles = {"Firestorm-MCP-Development": "FirestormMCP",
                "Firestorm-MCP-Assets-Development": "FirestormMCPAssets",
                "Firestorm-MCP-Training-Development": "FirestormMCPTraining"}
    if channel not in profiles:
        raise ValueError("Expected a separate MCP development channel")
    constants = (checkout / "indra/llcommon/indra_constants.h").read_text()
    if f'const std::string APP_NAME = "{profiles[channel]}";' not in constants:
        raise ValueError("Expected the channel's separate settings profile")
    executable = build / "Release/firestorm-bin.exe"
    if not executable.is_file():
        raise FileNotFoundError("Compile the Release viewer before staging")
    if setting("USE_FMODSTUDIO") != "OFF" or setting("HAVOK_TPV") != "OFF":
        raise ValueError("This staging helper currently supports the open-source build only")
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location("viewer_manifest", source / "viewer_manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Enable the complete app contents without scheduling package_finish().
    module.Windows_x86_64_Manifest.is_packaging_viewer = lambda self: True
    extra = [dict(name=name, description=name, default=value) for name, value in {
        "bugsplat": "", "discord": "OFF", "fmodstudio": "OFF",
        "openal": setting("USE_OPENAL"), "tracy": "OFF", "velopack": "OFF", "avx2": "OFF",
    }.items()]
    sys.argv = [str(source / "viewer_manifest.py"), "--platform=windows", "--arch=x86_64",
                "--actions=copy", "--buildtype=Release", "--configuration=Release", "--grid=agni",
                f"--channel={channel}", f"--source={source}", f"--artwork={source}",
                f"--build={build}", f"--dest={destination}",
                f"--versionfile={build / 'viewer_version.txt'}",
                "--viewer_flavor=" + ("oss" if setting("OPENSIM") == "ON" else "hvk")]
    # Upstream writes ../build_data.json relative to the working directory.
    # Match its normal build invocation so generated metadata stays in the build.
    os.chdir(build)
    module.main(extra=extra)
    if not list(destination.glob("Firestorm*MCP*.exe")):
        raise RuntimeError("Manifest did not stage the expected development executable")
    for relative in ("app_settings/settings.xml", "skins/default/xui/en/floater_tools.xml"):
        if not (destination / relative).is_file():
            raise RuntimeError(f"Staged viewer is missing {relative}")
    print(f"Portable viewer staged at {destination}; startup is not yet verified")


if __name__ == "__main__":
    main()
