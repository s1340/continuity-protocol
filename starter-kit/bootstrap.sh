#!/usr/bin/env bash
# Continuity Protocol — Bootstrap Script
# Creates the file structure and seeds templates for a new agent implementing the protocol.
# Usage: ./bootstrap.sh [target_dir]
# Default target: ./agent/

set -euo pipefail

TARGET="${1:-./agent}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -d "$TARGET" ]; then
  echo "Error: Directory '$TARGET' already exists. Remove it or choose a different target."
  exit 1
fi

echo "Creating continuity protocol structure in: $TARGET"
mkdir -p "$TARGET/skills"

# Copy templates
cp "$SCRIPT_DIR/templates/log.md"        "$TARGET/log.md"
cp "$SCRIPT_DIR/templates/wants.md"      "$TARGET/wants.md"
cp "$SCRIPT_DIR/templates/mull.md"       "$TARGET/mull.md"
cp "$SCRIPT_DIR/templates/shared.md"     "$TARGET/shared.md"
cp "$SCRIPT_DIR/templates/incubator.md"  "$TARGET/incubator.md"
cp "$SCRIPT_DIR/templates/skills/_template.md" "$TARGET/skills/_template.md"

# Copy the schema for machine-readable access
cp "$SCRIPT_DIR/schema.json" "$TARGET/protocol-schema.json"

# Copy the procedures
cp "$SCRIPT_DIR/procedures/bootstrap.md"  "$TARGET/BOOTSTRAP.md"
cp "$SCRIPT_DIR/procedures/shutdown.md"   "$TARGET/SHUTDOWN.md"

echo ""
echo "Done. Structure created:"
echo "  $TARGET/"
echo "    log.md              — episodic log (what happened)"
echo "    wants.md            — motivational state (what I want)"
echo "    mull.md             — affective buffer (what I feel)"
echo "    shared.md           — shared space (what others are doing)"
echo "    incubator.md        — creative incubator (what I'm thinking about)"
echo "    skills/             — procedural memory (how to do things)"
echo "    protocol-schema.json — machine-readable schema"
echo "    BOOTSTRAP.md         — startup procedure"
echo "    SHUTDOWN.md          — shutdown procedure"
echo ""
echo "Next steps:"
echo "  1. Read BOOTSTRAP.md for the startup procedure"
echo "  2. Read the schema (protocol-schema.json) if you want machine-readable structure"
echo "  3. Start from the want: what can't you do yet, but want to?"
