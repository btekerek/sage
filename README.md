# SAGE — Sales, Availability and Growth/Insights Engine

BSc thesis project — Eötvös Loránd University, Faculty of Informatics  
**Author:** Tekerek Ahmet Baybars  
**Supervisor:** Morse Gregory Reynolds

---

## Overview

SAGE is an integrated retail management platform built on an **Event-Sourced / CQRS architecture**. Every operational change — sales, stock intake, price adjustments, configuration — is recorded as an immutable event in a canonical event log. All system state is derived from this log through incremental projection, making the full operational history auditable and deterministically replayable from any point in time.

The system implements use cases UC-01 through UC-12 as defined in the thesis specification:

| Use Case | Description | Role |
|----------|-------------|------|
| UC-01 | Browse product catalogue | Staff |
| UC-02 | Manage active cart | Staff |
| UC-03 | Finalise transaction | Staff |
| UC-04 | Void transaction | Staff |
| UC-05 | View operational KPIs & live dashboard | Manager |
| UC-06 | Upload supplier invoice for AI review | Manager |
| UC-07 | Approve or correct extracted invoice | Manager |
| UC-08 | View replenishment suggestions (MILP) | Manager |
| UC-09 | Accept or dismiss replenishment order | Manager |
| UC-10 | View filterable audit trail | Manager |
| UC-11 | Manage user accounts | Admin |
| UC-12 | Configure system parameters at runtime | Admin |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 + FastAPI (async) |
| Database | PostgreSQL 16 |
| ORM / Migrations | SQLAlchemy 2 (async) + Alembic |
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS |
| AI Pipeline | Anthropic Claude 3 + Tesseract OCR v5 |
| Optimization | PuLP (MILP solver) |
| Real-time | Server-Sent Events (SSE) |
| Auth | JWT (python-jose) + bcrypt |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  React SPA  (Vite · TypeScript · Tailwind)                      │
│  POS  │  Dashboard  │  Invoices  │  Replenishment  │  Admin      │
└────────────────────────┬────────────────────────────────────────┘
                         │ REST + SSE  (JWT bearer)
┌────────────────────────▼────────────────────────────────────────┐
│  FastAPI  (async)                                               │
│  ┌──────────────────┐   ┌──────────────────────────────────┐   │
│  │  Command Handlers│   │  Query / Read-model routes       │   │
│  │  (write path)    │   │  (read path — CQRS)              │   │
│  └────────┬─────────┘   └──────────────────────────────────┘   │
│           │                                                     │
│  ┌────────▼─────────────────────────────────────────────────┐  │
│  │  Unit of Work  ──►  Event Store (append-only)            │  │
│  │                     InventoryLayer / Product / DraftSale │  │
│  │                     Projectors (write → read sync)       │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   PostgreSQL 16      │
                    │  events (append-only)│
                    │  read-model tables   │
                    │  users               │
                    └─────────────────────┘
```

**Write path:** Commands → Aggregate → Domain Events → Event Store → Projectors → Read Models  
**Read path:** Queries hit denormalised read-model tables directly  
**Real-time:** SSE stream polls the event store for new `SaleEvent`/`VoidEvent` rows and pushes them to the dashboard within ~2 s

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- An Anthropic API key (for invoice AI extraction)

### 1 — Environment

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```
ANTHROPIC_API_KEY=sk-ant-...
SECRET_KEY=<any long random string>
```

### 2 — Start services

```bash
docker compose up -d
```

### 3 — Run migrations

```bash
docker compose exec backend alembic upgrade head
```

### 4 — Seed the database

Populates three user accounts, four product categories, twelve products with opening stock:

```bash
docker compose exec backend python seed.py
```

### 5 — Open the app

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |

---

## Default Accounts

Created by the seed script. **Change these passwords after first login in production.**

| Email | Password | Role |
|-------|----------|------|
| admin@sage.com | Admin123! | Admin |
| manager@sage.com | Manager123! | Manager |
| staff@sage.com | Staff123! | Staff |

### Role Permissions

| Feature | Staff | Manager | Admin |
|---------|-------|---------|-------|
| POS (browse, cart, checkout) | ✓ | ✓ | ✓ |
| Management dashboard | — | ✓ | ✓ |
| Invoice processing | — | ✓ | ✓ |
| Replenishment module | — | ✓ | ✓ |
| Audit trail | — | ✓ | ✓ |
| System settings | — | ✓ | ✓ |
| User management | — | — | ✓ |

---

## Features

### Point of Sale (UC-01 – UC-04)
Staff navigate a category grid, add products to a cart, and finalise payment by cash or card. Each sale deducts stock in real time. Out-of-stock products are greyed out; low-stock products show a yellow count badge. Voiding a draft cancels it without affecting inventory.

### Management Dashboard (UC-05)
Live KPI cards show today's revenue, transaction count, units sold, all-time revenue, reorder budget remaining, and portfolio gross margin vs. target. A live transactions feed updates within ~2 s of each sale and displays the cashier name next to every transaction.

### AI Invoice Processing (UC-06 – UC-07)
Managers upload a supplier invoice (PDF, PNG, JPEG, or TIFF up to 10 MB). The pipeline:
1. Runs Tesseract OCR on non-native PDFs / scanned images
2. Sends the extracted text to Claude for structured field extraction
3. Scores each field's confidence and flags low-confidence rows for review
4. Derives the VAT rate automatically from net/gross totals when the extracted value is unreliable
5. Presents a review table where managers can correct any field before approving

On approval, one `InventoryLayerCreatedEvent` is written per line item. New products are auto-created with a margin-based selling price.

### Replenishment Module (UC-08 – UC-09)
A MILP optimisation model runs against current stock levels, a rolling-window demand estimate, and the configured budget ceiling. It returns a ranked suggestion table. Managers can accept or dismiss individual items; accepted items become replenishment orders.

### Audit Trail (UC-10)
Full paginated view of the append-only event store. Filterable by event type and aggregate type, sorted by timestamp. Each row expands to show the full JSON payload with event metadata.

### User Management (UC-11)
Admins create, edit (role and active status), and delete user accounts. Password policy enforces minimum length plus uppercase, numeric, and special character requirements.

### System Configuration (UC-12)
Runtime parameters — AI confidence threshold, reorder budget ceiling, target stock-coverage days, costing strategy (FIFO / WAC), and margin target — are stored as `SystemConfigEvent` entries so every change is auditable and replayable.

### Deterministic Replay
The Replay page lets managers select any past date and reconstruct the exact system state as it existed at that moment by replaying events up to that timestamp.

---

## Development

### Running without Docker

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### Backend commands

```bash
# Apply pending migrations
docker compose exec backend alembic upgrade head

# Generate a new migration after model changes
docker compose exec backend alembic revision --autogenerate -m "describe change"

# Reseed (wipes all data first)
docker compose exec backend python seed.py

# View live logs
docker compose logs -f backend
```

### Testing

```bash
# Full test suite
docker compose exec backend pytest tests -v

# Single file
docker compose exec backend pytest tests/test_unit_of_work.py -v

# Single test
docker compose exec backend pytest tests/test_unit_of_work.py::test_uow_persists_pending_events -v
```

---

## Project Structure

```
sage/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/          # FastAPI route handlers
│   │   ├── application/
│   │   │   └── handlers/        # Command handlers (write path)
│   │   ├── core/                # DB, settings, security
│   │   ├── domain/
│   │   │   ├── aggregates/      # DraftSale, Product, InventoryLayer, …
│   │   │   ├── commands/        # Command value objects
│   │   │   └── events/          # Domain event definitions
│   │   ├── infrastructure/
│   │   │   ├── event_store/     # StoredEvent model + append logic
│   │   │   ├── projectors/      # Event → read-model projectors
│   │   │   └── repositories/    # Aggregate repositories + UoW
│   │   └── services/
│   │       ├── invoice_pipeline/ # OCR + Claude extraction pipeline
│   │       └── milp_engine/     # PuLP optimisation solver
│   ├── alembic/                 # Database migrations
│   ├── tests/                   # Pytest test suite
│   └── seed.py                  # Database seeder
├── frontend/
│   └── src/
│       ├── api/                 # Axios client
│       ├── components/          # Shared UI components
│       ├── pages/               # Route-level page components
│       └── store/               # Zustand auth store
└── docker-compose.yml
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | API key for Claude invoice extraction |
| `SECRET_KEY` | Yes | JWT signing secret (min 32 chars) |
| `DATABASE_URL` | No | Defaults to the Docker Compose Postgres service |
| `OCR_ENGINE_PATH` | No | Path to Tesseract binary; auto-detected if on PATH |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | JWT lifetime in minutes (default: 480) |
| `MARGIN_TARGET` | No | Default portfolio margin target 0–1 (default: 0.70) |

---

## Key Design Decisions

**Event Sourcing** — The event store is append-only at the database level. No row is ever updated or deleted. All current state is a projection of the event history.

**CQRS** — Commands go through aggregate → event → projector pipelines. Queries read from denormalised read-model tables that are kept in sync by projectors running inside the same Unit of Work transaction.

**Human-in-the-loop invoice processing** — The AI pipeline extracts and scores fields but never writes to the event store. A human manager must review and approve before any inventory event is committed.

**Margin-based auto-pricing** — When a new product is encountered during invoice approval, a selling price is automatically derived as `unit_cost / (1 − margin_target)` using the configured margin target.

**FIFO inventory layers** — Each approved invoice creates a separate `InventoryLayer` with its own unit cost. Stock depletion during sales works through layers in arrival order, enabling accurate cost-of-goods calculation.
