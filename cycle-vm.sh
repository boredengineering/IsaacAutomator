#!/bin/bash
# cycle-vm.sh - Convenience wrapper for ./cycle-vm
# Usage: ./cycle-vm.sh <deployment_name> [options...]

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$REPO_ROOT/cycle-vm" "$@"
