#!/bin/sh
set -eu
mkdir -p _site
cp index.html .nojekyll _site/
cp -R assets data _site/
# E-commerce is available only through the private, authenticated Docker backend.
rm -f _site/data/ecom.json*
