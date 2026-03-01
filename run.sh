#!/usr/bin/env bash
# run.sh - Development build & run helper for Pasar
set -e

BUILDDIR="builddir"
PREFIX="$HOME/.local"

if [ ! -d "$BUILDDIR" ]; then
    echo "==> Setting up meson build..."
    meson setup "$BUILDDIR" --prefix="$PREFIX"
fi

echo "==> Building..."
ninja -C "$BUILDDIR"

echo "==> Installing to $PREFIX..."
ninja -C "$BUILDDIR" install

echo "==> Launching Pasar..."
exec env GSETTINGS_SCHEMA_DIR="$HOME/.local/share/glib-2.0/schemas" \
    "$HOME/.local/bin/pasar"
