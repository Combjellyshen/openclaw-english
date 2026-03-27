#!/usr/bin/env bash
# smudge filter: runs on git checkout — restores real values from placeholders
sed \
  -e 's/<YOUR_NAME>/Combjelly Shen/g' \
  -e 's/<YOUR_NICKNAME>/Combjelly/g'
