#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt
python manage.py makemigrations distribution
python manage.py migrate
python manage.py seed_data
python manage.py collectstatic --no-input
