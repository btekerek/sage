# SAGE — Sales, Availability and Growth/Insights Engine

BSc thesis project — Eötvös Loránd University, Faculty of Informatics  
**Author:** Tekerek Ahmet Baybars  
**Supervisor:** Morse Gregory Reynolds

## Overview

SAGE is an integrated retail management platform built on an Event-Sourced Architecture.
Every operational change — sales, stock intake, price adjustments — is recorded as an
immutable event in a canonical event log. All system state is derived from this log
through incremental projection.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 + FastAPI |
| Database | PostgreSQL 16 |
| Frontend | React 18 + TypeScript + Vite |
| AI Pipeline | Anthropic Claude + Tesseract OCR v5 |
| Optimization | PuLP (MILP solver) |
| Real-time | WebSockets (FastAPI native) |

## Setup
```bash
# 1. Copy environment variables
cp .env.example .env
# Edit .env with your values

# 2. Start with Docker
docker compose up

# OR manually:

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```