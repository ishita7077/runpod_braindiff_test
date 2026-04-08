#!/usr/bin/env bash
set -euo pipefail

mkdir -p "atlases"
curl -L "https://ndownloader.figshare.com/files/5528816" -o "atlases/lh.HCP-MMP1.annot"
curl -L "https://ndownloader.figshare.com/files/5528819" -o "atlases/rh.HCP-MMP1.annot"

echo "Downloaded:"
ls -lh "atlases/lh.HCP-MMP1.annot" "atlases/rh.HCP-MMP1.annot"

