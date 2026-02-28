#!/bin/bash
gunicorn --bind=0.0.0.0:${PORT:-8000} --timeout 600 --workers 1 app:app
