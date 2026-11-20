#!/usr/bin/env bash
set -e

IP="127.0.0.1"
PORT="8080"
COUNT="100"

while [[ $# -gt 0 ]]; do
  case "$1" in
  --ip)
    IP="$2"
    shift 2
    ;;
  --port)
    PORT="$2"
    shift 2
    ;;
  --count)
    COUNT="$2"
    shift 2
    ;;
  *)
    echo "未知参数: $1"
    exit 1
    ;;
  esac
done

python3 generate.py "$COUNT" "http://${IP}:${PORT}"
