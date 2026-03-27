#!/usr/bin/env bash
# clean filter: runs on git add — replaces real values with placeholders
sed \
  -e 's/Combjelly Shen/<YOUR_NAME>/g' \
  -e 's/Combjelly/<YOUR_NICKNAME>/g'
