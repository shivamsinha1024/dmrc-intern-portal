#!/bin/bash
# ---------------------------------------------------------------------------
# vendorize.sh
#
# Downloads every CDN-hosted library used by the DMRC portal into a local
# "vendor" folder inside EACH phase folder, so both pages work offline.
#
# RUN THIS FROM INSIDE THE "Front End" FOLDER, WITH INTERNET ON:
#     cd "/path/to/Front End"
#     bash vendorize.sh
#
# It does NOT modify any HTML. Editing the HTML is a separate, manual step.
# Re-running it is safe: it just overwrites the downloaded files.
# ---------------------------------------------------------------------------

set -euo pipefail

# --- Pinned versions -------------------------------------------------------
BS_VER=5.3.3        # Bootstrap          (unchanged from your HTML)
BSI_VER=1.11.3      # Bootstrap Icons    (unchanged from your HTML)
FP_VER=4.6.13       # flatpickr          (was floating; latest, unchanged since 2022)
ALPINE_VER=3.16.2   # Alpine.js          (was 3.x.x, which already resolves to this)

JD="https://cdn.jsdelivr.net/npm"
PHASES=("Phase-1-User-Portal" "Phase-2-HR-Dashboard")

# --- Safety check: are we in the right directory? --------------------------
for p in "${PHASES[@]}"; do
  if [ ! -d "$p" ]; then
    echo ""
    echo "ERROR: Cannot find the folder '$p' here."
    echo "You are currently in: $(pwd)"
    echo "Please 'cd' into the 'Front End' folder and run this again."
    echo ""
    exit 1
  fi
done

# --- Download helper: fails loudly instead of saving an error page ---------
get() {
  # get <url> <destination-file>
  printf '   %-52s' "$(basename "$2")"
  if curl -fsSL --retry 3 --retry-delay 2 -o "$2" "$1"; then
    printf 'ok  (%s)\n' "$(du -h "$2" | cut -f1 | tr -d ' ')"
  else
    printf 'FAILED\n'
    echo ""
    echo "ERROR: could not download:"
    echo "   $1"
    echo "Check your internet connection and run the script again."
    exit 1
  fi
}

echo ""
echo "==========================================================="
echo " Vendoring libraries into both phase folders"
echo " Bootstrap $BS_VER | Bootstrap Icons $BSI_VER"
echo " flatpickr $FP_VER | Alpine.js $ALPINE_VER"
echo "==========================================================="

# --- Libraries: one full copy per phase folder -----------------------------
for p in "${PHASES[@]}"; do
  V="$p/vendor"
  mkdir -p "$V/bootstrap" "$V/bootstrap-icons/fonts" "$V/flatpickr" "$V/alpine"

  echo ""
  echo "-- $p --"

  # Bootstrap CSS + JS (plus source maps, so DevTools shows no 404s)
  get "$JD/bootstrap@$BS_VER/dist/css/bootstrap.min.css"          "$V/bootstrap/bootstrap.min.css"
  get "$JD/bootstrap@$BS_VER/dist/css/bootstrap.min.css.map"      "$V/bootstrap/bootstrap.min.css.map"
  get "$JD/bootstrap@$BS_VER/dist/js/bootstrap.bundle.min.js"     "$V/bootstrap/bootstrap.bundle.min.js"
  get "$JD/bootstrap@$BS_VER/dist/js/bootstrap.bundle.min.js.map" "$V/bootstrap/bootstrap.bundle.min.js.map"

  # Bootstrap Icons: CSS *and* the two font files it points at.
  # The CSS expects them at "./fonts/" relative to itself - hence the layout.
  get "$JD/bootstrap-icons@$BSI_VER/font/bootstrap-icons.css"           "$V/bootstrap-icons/bootstrap-icons.css"
  get "$JD/bootstrap-icons@$BSI_VER/font/fonts/bootstrap-icons.woff2"   "$V/bootstrap-icons/fonts/bootstrap-icons.woff2"
  get "$JD/bootstrap-icons@$BSI_VER/font/fonts/bootstrap-icons.woff"    "$V/bootstrap-icons/fonts/bootstrap-icons.woff"

  # flatpickr
  get "$JD/flatpickr@$FP_VER/dist/flatpickr.min.css" "$V/flatpickr/flatpickr.min.css"
  get "$JD/flatpickr@$FP_VER/dist/flatpickr.min.js"  "$V/flatpickr/flatpickr.min.js"

  # Alpine.js - MUST be the "cdn" build. The module builds do not self-start.
  get "$JD/alpinejs@$ALPINE_VER/dist/cdn.min.js" "$V/alpine/cdn.min.js"
done

# --- Google Fonts: Phase-1 only (Phase-2 never loaded them) ----------------
# Google serves different CSS to different browsers. We pretend to be Chrome
# so we get modern .woff2 files, then keep only the latin + latin-ext blocks.
echo ""
echo "-- Google Fonts (Inter + Sora) -> Phase-1 only --"

FV="Phase-1-User-Portal/vendor/fonts"
mkdir -p "$FV/files"

UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
GF_URL="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Sora:wght@600;700;800&display=swap"

printf '   %-52s' "google stylesheet"
if curl -fsSL -A "$UA" -o "$FV/.raw.css" "$GF_URL"; then
  printf 'ok\n'
else
  printf 'FAILED\n'; echo "ERROR: could not reach fonts.googleapis.com"; exit 1
fi

# Keep only the @font-face blocks labelled /* latin */ and /* latin-ext */
awk '/^\/\* .* \*\/$/ { keep = ($2 == "latin" || $2 == "latin-ext") } keep { print }' \
  "$FV/.raw.css" > "$FV/fonts.css"

# Fallback: if the filter matched nothing, keep the whole stylesheet
if [ ! -s "$FV/fonts.css" ]; then
  echo "   (subset comments not found - keeping all subsets instead)"
  cp "$FV/.raw.css" "$FV/fonts.css"
fi

# Download each font file referenced by the filtered CSS
grep -o 'https://fonts\.gstatic\.com[^)]*' "$FV/fonts.css" | sort -u | while read -r u; do
  get "$u" "$FV/files/$(basename "$u")"
done

# Repoint the CSS at the local copies
sed -i '' -E 's#https://fonts\.gstatic\.com/[^)]*/([^/)]+)#files/\1#g' "$FV/fonts.css"
rm -f "$FV/.raw.css"

# --- Post-download sanity checks -------------------------------------------
echo ""
echo "==========================================================="
echo " Checks"
echo "==========================================================="

fail=0

# 1. Alpine is the critical dependency - confirm we got a real build.
if grep -q "Alpine" "Phase-1-User-Portal/vendor/alpine/cdn.min.js" 2>/dev/null; then
  echo " [ok]   Alpine build contains expected code"
else
  echo " [FAIL] Alpine file looks wrong - the pages will not work"; fail=1
fi

# 2. Icon fonts present and plausibly sized
for p in "${PHASES[@]}"; do
  f="$p/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2"
  if [ -f "$f" ] && [ "$(wc -c < "$f")" -gt 50000 ]; then
    echo " [ok]   Icon font present in $p"
  else
    echo " [FAIL] Icon font missing/short in $p - icons will be empty boxes"; fail=1
  fi
done

# 3. Font files downloaded
n=$(ls -1 "$FV/files" 2>/dev/null | wc -l | tr -d ' ')
echo " [info] Web font files downloaded: $n"
[ "$n" -gt 0 ] || { echo " [FAIL] No font files downloaded"; fail=1; }

# 4. No leftover internet references inside the fonts CSS
if grep -q "fonts.gstatic.com" "$FV/fonts.css"; then
  echo " [FAIL] fonts.css still points at the internet"; fail=1
else
  echo " [ok]   fonts.css points only at local files"
fi

# 5. Anything suspiciously small is probably a saved error page
small=$(find Phase-1-User-Portal/vendor Phase-2-HR-Dashboard/vendor -type f -size -1k 2>/dev/null || true)
if [ -n "$small" ]; then
  echo " [warn] These files are under 1 KB - open them and check they aren't error pages:"
  echo "$small" | sed 's/^/          /'
fi

echo ""
if [ "$fail" -eq 0 ]; then
  echo " All checks passed. Now make the HTML edits."
else
  echo " SOMETHING FAILED ABOVE - fix it before editing the HTML."
  exit 1
fi
echo ""
