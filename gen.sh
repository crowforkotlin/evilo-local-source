#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
IP=""
BASE=""
PORT="8080"
COUNT="10"
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ip|--port|--count|--base-url)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 1; }
      case "$1" in
        --ip) IP="$2" ;;
        --port) PORT="$2" ;;
        --count) COUNT="$2" ;;
        --base-url) BASE="$2" ;;
      esac
      shift 2
      ;;
    --signing-key-directory|--subscription-key-directory|--template|--sdk-path|--wasmline-path|--works|--batch-size)
      [[ $# -ge 2 ]] || { printf 'Missing value for %s\n' "$1" >&2; exit 1; }
      EXTRA+=("$1" "$2")
      shift 2
      ;;
    --auto-download|--use-local-sdk)
      EXTRA+=("$1")
      shift
      ;;
    --help|-h)
      printf 'Usage: bash gen.sh --ip HOST [--port 8080] [--count 10] --signing-key-directory DIR\n'
      printf 'Or use --base-url http://HOST:8080. Builds fixtures only; serve.py starts HTTP separately.\n'
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

[[ -z "$IP" || -z "$BASE" ]] || { printf 'Use either --ip or --base-url, not both\n' >&2; exit 1; }
if [[ -z "$BASE" ]]; then
  [[ -n "$IP" ]] || { printf 'Supply --ip or --base-url explicitly; no loopback default\n' >&2; exit 1; }
  [[ "$IP" != *:* || "$IP" == \[*\] ]] || IP="[$IP]"
  BASE="http://${IP}:${PORT}"
fi
exec python3 -I "$ROOT/generate.py" "$COUNT" "$BASE" "${EXTRA[@]}"
