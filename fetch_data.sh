#!/usr/bin/env bash
# Clone public data sources at the commits used for the published backtest.
set -euo pipefail
mkdir -p "$(dirname "$0")/data/raw"
cd "$(dirname "$0")/data/raw"
clone() { [ -d "$2" ] || git clone --filter=blob:none "$1" "$2"; git -C "$2" fetch -q origin; git -C "$2" checkout -q "${3:-origin/HEAD}"; }
# Pinned commits reproduce outputs/. Pass --latest to use the newest data instead.
if [ "${1:-}" = "--latest" ]; then P1=origin/HEAD; P2=origin/HEAD; P3=origin/HEAD; else P1=25882a58a736daf7ece3781940eac17ae1117a66; P2=e6744429ee395bc86f247348c6184bb08d4eb361; P3=abfaeddc2ee3d14f99ecc163c9ddb46cb4d67cef; fi
clone https://github.com/xgabora/Club-Football-Match-Data-2000-2025.git cfmd "$P1"
clone https://github.com/openfootball/football.json.git fj "$P2"
clone https://github.com/openfootball/champions-league.git ucl "$P3"
echo "data ready"
