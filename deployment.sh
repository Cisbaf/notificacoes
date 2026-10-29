#!/bin/bash
set -e
cd "$(dirname "$0")"
# Sem remoto configurado (repo só local), pula o pull.
if [ -n "$(git remote)" ]; then git pull; fi
docker compose build
docker compose up -d --remove-orphans
