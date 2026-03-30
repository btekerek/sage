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
# 1. Copy and fill in environment variables
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY and SECRET_KEY

# 2. Start all services
docker compose up -d

# 3. Run database migrations
docker compose exec backend alembic upgrade head
```

## Running

```bash
# Start only the database and backend (skip frontend)
docker compose up -d db backend

# Start everything including frontend
docker compose up -d

# View backend logs
docker compose logs -f backend

# Stop all services
docker compose down
```

## API

Once running, the auto-generated API docs are available at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Health check: http://localhost:8000/health

## Testing

```bash
# Run the full test suite
docker compose exec backend pytest tests -v

# Run a specific test file
docker compose exec backend pytest tests/test_unit_of_work.py -v

# Run a specific test
docker compose exec backend pytest tests/test_unit_of_work.py::test_uow_persists_pending_events -v
```

## Manual setup (without Docker)

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```