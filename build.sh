#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

echo "--- Installing Python Dependencies ---"
pip install --upgrade pip
pip install -r requirements.txt

echo "--- Collecting Static Assets with WhiteNoise ---"
python manage.py collectstatic --no-input

echo "--- Applying Database Migrations ---"
python manage.py migrate --no-input

echo "--- Build Completed Successfully ---"
