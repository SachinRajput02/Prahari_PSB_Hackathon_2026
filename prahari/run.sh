#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
pip install -r requirements.txt
cd backend
python train_model.py        # trains model.pkl (skip if already present)
python seed.py                # seeds demo identities + mule ring
uvicorn app:app --host 0.0.0.0 --port 8000
