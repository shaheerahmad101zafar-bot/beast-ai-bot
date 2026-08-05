"""
Beast AI Trading Bot — Phase 11 Mobile Native Bundle Builder

Bundles the dashboard web UI into Capacitor + Cordova-compatible webview
structures so you can generate Android APK / iOS IPA packages with the
official native toolchains.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"
OUT_DEFAULT = ROOT / "mobile"


STATIC_ASSETS = [
    "index.html",
    "landing.html",
    "pricing.html",
    "styles.css",
    "landing.css",
    "app.js",
    "landing.js",
    "pricing.js",
    "charts.js",
    "pwa.js",
    "manifest.json",
    "service-worker.js",
]


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _rewrite_html(html: str, server_url: str) -> str:
    """Point absolute /static and API paths at the production origin when offline-bundled."""
    # Keep relative static paths inside the webview www root
    html = html.replace('href="/static/', 'href="./')
    html = html.replace('src="/static/', 'src="./')
    html = html.replace('href="/pricing"', 'href="./pricing.html"')
    html = html.replace('href="/app"', 'href="./index.html"')
    html = html.replace('href="/"', 'href="./landing.html"')
    # Inject runtime API base for Capacitor
    inject = f"""
  <script>
    window.BEAST_API_BASE = {json.dumps(server_url.rstrip("/"))};
    window.BEAST_NATIVE_SHELL = true;
  </script>
"""
    if "<head>" in html and "BEAST_API_BASE" not in html:
        html = html.replace("<head>", "<head>\n" + inject, 1)
    return html


def build_capacitor(out_dir: Path, app_id: str, app_name: str, server_url: str) -> Path:
    www = out_dir / "www"
    www.mkdir(parents=True, exist_ok=True)

    # Copy UI assets flattened into www/
    for name in STATIC_ASSETS:
        src = DASHBOARD / name
        if src.exists():
            shutil.copy2(src, www / name)
    icons = DASHBOARD / "icons"
    if icons.exists():
        _copy_tree(icons, www / "icons")

    # Rewrite HTML for local asset loading
    for page in ("index.html", "landing.html", "pricing.html"):
        path = www / page
        if path.exists():
            path.write_text(_rewrite_html(path.read_text(encoding="utf-8"), server_url), encoding="utf-8")

    # Capacitor config
    cap_config = {
        "appId": app_id,
        "appName": app_name,
        "webDir": "www",
        "server": {
            "url": server_url,
            "cleartext": server_url.startswith("http://"),
            "androidScheme": "https",
        },
        "plugins": {
            "SplashScreen": {
                "launchShowDuration": 1200,
                "backgroundColor": "#0f172a",
            },
        },
    }
    (out_dir / "capacitor.config.json").write_text(
        json.dumps(cap_config, indent=2), encoding="utf-8"
    )

    package = {
        "name": "beast-ai-mobile",
        "version": "11.0.0",
        "private": True,
        "description": "Beast AI Capacitor shell",
        "scripts": {
            "build:web": "echo Web assets are prebundled in www/",
            "cap:sync": "npx cap sync",
            "cap:android": "npx cap add android && npx cap sync android",
            "cap:ios": "npx cap add ios && npx cap sync ios",
            "open:android": "npx cap open android",
            "open:ios": "npx cap open ios",
        },
        "dependencies": {
            "@capacitor/android": "^6.2.0",
            "@capacitor/core": "^6.2.0",
            "@capacitor/ios": "^6.2.0",
            "@capacitor/splash-screen": "^6.0.2",
        },
        "devDependencies": {
            "@capacitor/cli": "^6.2.0",
        },
    }
    (out_dir / "package.json").write_text(json.dumps(package, indent=2), encoding="utf-8")

    readme = f"""# Beast AI Mobile (Capacitor)

Bundled from dashboard UI for native APK / IPA builds.

## Prerequisites
- Node.js 18+
- Android Studio (APK) and/or Xcode on macOS (IPA)

## Build
```bash
cd {out_dir.name}
npm install
npx cap add android   # once
npx cap add ios       # once (macOS)
npx cap sync
npx cap open android  # build APK/AAB in Android Studio
npx cap open ios      # build IPA in Xcode
```

API / WebSocket origin: `{server_url}`
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    return www


def build_cordova(out_dir: Path, app_id: str, app_name: str, server_url: str) -> Path:
    www = out_dir / "www"
    # Reuse capacitor www if already built
    if not www.exists():
        build_capacitor(out_dir, app_id, app_name, server_url)

    config_xml = f"""<?xml version='1.0' encoding='utf-8'?>
<widget id="{app_id}" version="11.0.0" xmlns="http://www.w3.org/ns/widgets"
        xmlns:cdv="http://cordova.apache.org/ns/1.0">
  <name>{app_name}</name>
  <description>Beast AI Trading Bot mobile shell</description>
  <author email="support@beast-ai.local" href="{server_url}">Beast AI</author>
  <content src="index.html" />
  <access origin="*" />
  <allow-intent href="http://*/*" />
  <allow-intent href="https://*/*" />
  <allow-navigation href="{server_url}/*" />
  <preference name="SplashScreenBackgroundColor" value="#0f172a" />
  <preference name="StatusBarBackgroundColor" value="#0f172a" />
  <platform name="android">
    <icon src="www/icons/icon-192.png" density="mdpi" />
    <icon src="www/icons/icon-512.png" density="xxxhdpi" />
  </platform>
  <platform name="ios">
    <icon src="www/icons/apple-touch-icon.png" width="180" height="180" />
  </platform>
</widget>
"""
    (out_dir / "config.xml").write_text(config_xml, encoding="utf-8")

    cordova_pkg = {
        "name": "beast-ai-cordova",
        "displayName": app_name,
        "version": "11.0.0",
        "private": True,
        "scripts": {
            "cordova:android": "cordova platform add android && cordova build android",
            "cordova:ios": "cordova platform add ios && cordova build ios",
        },
        "devDependencies": {
            "cordova": "^12.0.0",
        },
    }
    # Don't overwrite capacitor package.json if present — write sibling hint file
    (out_dir / "cordova.package.snippet.json").write_text(
        json.dumps(cordova_pkg, indent=2), encoding="utf-8"
    )
    return www


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bundle Beast AI UI for Capacitor/Cordova")
    parser.add_argument("--out", default=str(OUT_DEFAULT), help="Output directory (default: ./mobile)")
    parser.add_argument("--app-id", default="com.beastai.tradingbot", help="Native application id")
    parser.add_argument("--app-name", default="Beast AI", help="Display name")
    parser.add_argument(
        "--server-url",
        default="http://127.0.0.1:8000",
        help="Backend origin the WebView should call",
    )
    parser.add_argument(
        "--target",
        choices=("capacitor", "cordova", "both"),
        default="both",
        help="Scaffold target",
    )
    args = parser.parse_args(argv)

    if not DASHBOARD.exists():
        print("ERROR: dashboard/ folder missing", file=sys.stderr)
        return 1

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("  Beast AI Mobile Builder — Phase 11")
    print(f"  Out       : {out_dir}")
    print(f"  App ID    : {args.app_id}")
    print(f"  Server    : {args.server_url}")
    print(f"  Target    : {args.target}")
    print("=" * 64)

    if args.target in {"capacitor", "both"}:
        www = build_capacitor(out_dir, args.app_id, args.app_name, args.server_url)
        print(f"Capacitor www ready: {www}")
    if args.target in {"cordova", "both"}:
        www = build_cordova(out_dir, args.app_id, args.app_name, args.server_url)
        print(f"Cordova config ready: {out_dir / 'config.xml'}")

    # Inventory
    files = sorted(p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*") if p.is_file())
    print(f"Bundled {len(files)} files")
    for rel in files[:20]:
        print(f"  - {rel}")
    if len(files) > 20:
        print(f"  … {len(files) - 20} more")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
