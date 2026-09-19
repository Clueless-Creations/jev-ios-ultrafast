#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
demo_bundle="$project_root/runs/JevDemo.app"
simulator_sdk="$(xcrun --sdk iphonesimulator --show-sdk-path)"

mkdir -p "$demo_bundle"
cp "$project_root/demo/Info.plist" "$demo_bundle/Info.plist"
xcrun --sdk iphonesimulator swiftc \
  -sdk "$simulator_sdk" \
  -target arm64-apple-ios16.0-simulator \
  -parse-as-library -O \
  -framework UIKit \
  "$project_root/demo/App.swift" \
  -o "$demo_bundle/JevDemo"
codesign --force --sign - "$demo_bundle"
printf '%s\n' "$demo_bundle"
