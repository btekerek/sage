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
| AI Pipeline | Anthropic Claude Vision + Tesseract OCR v5 |
| Optimization | PuLP / CBC (MILP solver) |
| Real-time | Server-Sent Events (SSE) |
| Auth | JWT (python-jose) + bcrypt |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  React SPA  (Vite · TypeScript · Tailwind)                      │
│  POS  │  Dashboard  │  Invoices  │  Inventory  │  Admin          │
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
**Real-time:** SSE stream pushes `SaleEvent`/`VoidEvent` signals to all connected Dashboard clients within ~2 s

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

Populates user accounts and a 51-product bar menu catalog across 7 categories:

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
| Inventory & replenishment | — | ✓ | ✓ |
| Settings | — | ✓ | ✓ |
| Audit trail | — | ✓ | ✓ |
| User management | — | — | ✓ |
| Event replay | — | — | ✓ |

---

## Role-Based UI Themes

Every page and navbar is tinted according to the authenticated user's role, making the active access level immediately recognisable.

| Role | Colour Scheme | Navbar | Page Background |
|------|--------------|--------|-----------------|
| Staff / Cashier | Sky blue | `bg-sky-600` | `bg-sky-100` |
| Manager | Emerald green | `bg-emerald-700` | `bg-emerald-100` |
| Admin | Violet / Purple | `bg-violet-800` | `bg-violet-100` |

The theme is resolved at runtime from the `ROLE_THEME` lookup object exported from `NavBar.tsx` and applied globally by `AppLayout.tsx`.

### Login

![Login page](./screencaptures/1-staff-login.png)

*Figure 1 — Login page. The role-appropriate theme is applied immediately after authentication.*

---

## Features

### Point of Sale — UC-01 to UC-04

Staff navigate a category grid, add products to a cart, and finalise payment by cash or card. Each sale deducts stock in real time via `SaleEvent`. Out-of-stock products are greyed out. Voiding a draft emits a `VoidEvent` and leaves inventory unchanged.

![POS category selection](./screencaptures/2-staff-pos.png)

*Figure 2 — POS home screen showing the category tile grid (staff / sky theme).*

![POS product grid with cart](./screencaptures/3-staff-pos-cart.png)

*Figure 3 — POS product grid for Soft Drinks with an active cart, running total, and payment method selection.*

---

### Management Dashboard — UC-05

Live KPI cards show today's revenue, transaction count, units sold, all-time revenue, estimated reorder cost from the latest replenishment run, and portfolio gross margin versus target. A live transactions feed updates within ~2 s of each sale via SSE.

The replenishment suggestion table is embedded directly in the dashboard and refreshes automatically when an invoice is approved via the shared `InvoiceProcessor` component's `onLoad` callback.

The dashboard header is role-aware: **Manager Dashboard** for manager accounts, **Admin Dashboard** for admin accounts.

![Manager Dashboard](./screencaptures/4-manager-dashboard.png)

*Figure 4 — Manager Dashboard (emerald theme) showing KPI cards, live transactions feed, and MILP replenishment suggestions.*

![Admin Dashboard](./screencaptures/5-admin-dashboard.png)

*Figure 5 — Admin Dashboard (violet theme) with the same MILP replenishment panel.*

---

### AI Invoice Processing — UC-06 to UC-07

Managers upload a supplier invoice (PDF, PNG, JPEG, or TIFF up to 10 MB). The three-stage pipeline:

1. **Layout analysis** — pdfplumber extracts column-aware text layout; Tesseract OCR is used as a fallback for scanned documents
2. **Field extraction** — Claude Vision reconciles the layout summary against rendered page images to extract product name, quantity, unit price, VAT rate, and line total, each with a per-field confidence score
3. **Validation & routing** — numeric constraints are checked; fields below the confidence threshold or failing validation are flagged for human review

On approval, one `InventoryIntakeEvent` is written per line item. New products encountered for the first time are auto-created with a margin-derived selling price (`unit_cost / (1 − margin_target)`). After approval, the replenishment suggestions panel refreshes automatically across both the Dashboard and Inventory pages.

![Invoice Processing](./screencaptures/6-manager-invoice.png)

*Figure 6 — Invoice Processing page (emerald theme). Upper panel handles document upload and AI extraction; lower panel shows the approval history.*

---

### Replenishment Module — UC-08 to UC-09

#### MILP Solver

The replenishment engine uses a **Mixed-Integer Linear Programme** (PuLP / CBC) to determine optimal order quantities for all products below their target stock horizon.

**Model formulation:**

For each product *i* where `current_stock < daily_demand × (lead_time_days + target_coverage_days)`:

- Decision variable: `x_i ∈ ℤ≥0` — units to order
- **Objective:** minimise `Σ (unit_cost_i × x_i)` (minimum-cost replenishment)
- **Coverage constraint:** `current_stock_i + x_i ≥ daily_demand_i × (lead_time_days_i + target_coverage_days_i)` ∀ i
- **Budget constraint:** `Σ (unit_cost_i × x_i) ≤ weekly_budget`

Since `x_i = 0` always satisfies the coverage constraint, the LP is always feasible and the solver always returns `Optimal`. When the budget is binding, lower-urgency products may receive reduced order quantities and the panel surfaces `budget_constrained = True`. Products with zero daily demand are excluded from the candidate set.

#### Per-Product Replenishment Overrides

Each product can have individual `lead_time_days` and `target_coverage_days` values set via the inline editor on the Inventory page. The resolution order at solve time is:

```
product override  →  global system config
```

Leaving either field blank on a product falls back to the global values from Settings. This allows perishables to use a short 7-day coverage horizon while non-perishables use the 30-day default, without requiring separate product groups.

The `ReplenishmentSuggestions` component is shared between the Dashboard and the Inventory page — both consume the same `/api/replenishment/suggestions` endpoint.

![Inventory with replenishment](./screencaptures/7-manager-inventory.png)

*Figure 7 — Inventory page (emerald theme) showing the MILP replenishment suggestions panel and the full product table.*

---

### Inventory Page

The Inventory page provides a full view of current stock positions and demand signals for every product in the catalogue.

**Table columns:**

| Column | Description |
|--------|-------------|
| Product | Name and category |
| On Hand | Total current stock across all cost layers |
| Avg Daily Demand | Rolling demand rate derived from recent `SaleEvent`s; `—` if no sales history |
| Days Left | Estimated days until stockout at current demand; `—` if demand is zero |
| Lead Time | Per-product override (days); grey badge = using global default |
| Cover Days | Per-product override (days); grey badge = using global default |
| Unit Cost | Most recent acquisition cost from the latest inventory layer |

**Inline editor** (click the edit icon on any row): set or clear per-product `lead_time_days` and `target_coverage_days` overrides. Leave blank to revert to the global default.

**Add Product form**: new products can be created directly from the Inventory page with an optional lead time and cover days preset.

---

### Settings Page — UC-12

Managers and admins adjust runtime parameters. All changes are persisted as `SystemConfigEvent` entries in the event store, making every configuration change fully auditable and replayable.

| Parameter | Default | Description |
|-----------|---------|-------------|
| AI confidence threshold | 0.65 | Minimum per-field confidence score for auto-accepting extracted invoice fields |
| Margin target | 0.70 | Used to auto-derive selling prices for new products during invoice approval |
| Target coverage days | 30 | Days of forward stock the replenishment engine aims to cover beyond the lead time |
| Supplier lead time (days) | 3 | Global default days from order placement to goods receipt; added to target days in the coverage constraint |
| Weekly budget | 150,000 | Maximum total spend per replenishment run (HUF); when binding, the solver deprioritises lower-urgency products |
| Costing strategy | FIFO | Inventory valuation method — FIFO or WAC (weighted average) |

![Settings page](./screencaptures/8-manager-settings.png)

*Figure 8 — Settings page (emerald theme) showing all configurable runtime parameters.*

---

### Audit Trail — UC-10

Full paginated view of the append-only event store. Filterable by event type, sorted by descending timestamp. Each row expands to reveal the full JSON payload with event metadata (event ID, sequence number, causation ID, actor ID).

![Audit Trail](./screencaptures/9-admin-audit-trail.png)

*Figure 9 — Audit Trail page (violet / admin theme) showing the event log with type filters and expandable payload rows.*

---

### Deterministic Replay

The Replay page lets admins select any past date and reconstruct the exact system state as it existed at that moment by replaying events up to that timestamp — demonstrating the core event-sourcing guarantee that any historical snapshot is deterministically reproducible from sequence 0.

![Replay page](./screencaptures/10-admin-replay.png)

*Figure 10 — Replay page with the date-picker control for historical state reconstruction.*

---

### User Management — UC-11

Admins have a full-width user management panel with KPI summary cards and a detailed user table.

**KPI cards:** Total Users · Active · Admins · Managers · Staff

**Table columns:**

| Column | Description |
|--------|-------------|
| User | Email address and shortened UUID |
| Role | Colour-coded role badge (violet = admin, emerald = manager, sky = staff) |
| Screen Access | Chips showing which pages the account can reach |
| Status | Active (green dot) or Inactive (grey dot) |
| Created | Account creation timestamp |
| Last Modified | Most recent profile update timestamp |
| Actions | Edit (inline form with optional password reset) and Delete |

Password policy: minimum 8 characters including at least one uppercase letter, one digit, and one special character. Admins cannot deactivate or demote their own account.

![User Management](./screencaptures/11-admin-user-management.png)

*Figure 11 — User Management page (violet / admin theme) showing KPI cards and the full-width user table.*

---

## Seed Data — Bar Menu Catalog

The seed script (`backend/seed.py`) creates a coherent **bar menu** catalog of 51 products across 7 categories. All selling prices are derived from cost using the 70% default margin target (`selling = cost / (1 − 0.70)`).

| Category | Count | Example Products |
|----------|-------|-----------------|
| Soft Drinks | 10 | Coca-Cola, Red Bull, Schweppes Tonic, Nestea Ice Tea |
| Beer | 8 | Dreher Arany, Heineken, Hoegaarden, Guinness Draught |
| Wine & Sparkling | 8 | Egri Bikavér, Tokaji Furmint, Törley Chardonnay, Prosecco DOC |
| Spirits | 8 | Unicum, Pálinka Körte, Jack Daniel's, Beefeater Gin |
| Sweet Snacks | 7 | Milka Oreo Bar, Snickers, Ferrero Rocher 3-pack |
| Salty Snacks | 7 | Lay's Classic, Pringles Original, Mixed Nuts 50g |
| Bar Food | 7 | Hot Dog, Chicken Wings 6pcs, Nachos with Salsa |

---

## Navigation Structure

The navbar adapts to the authenticated user's role and is colour-coded accordingly.

**Manager / Admin navigation:**  
Dashboard → Inventory → Invoices → Replay → *(Audit Trail)* → *(User Management)* → Settings

Items in parentheses are shown only for admin accounts. Both manager and admin accounts have a **POS** quick-access button in the top-right navbar area to switch to the cashier interface without logging out.

**Staff navigation:** POS link only.

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
# Apply all pending migrations
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
docker compose exec backend pytest

# Verbose output
docker compose exec backend pytest -v

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
│   │   │   └── routes/           # FastAPI route handlers
│   │   │       ├── auth.py
│   │   │       ├── categories.py
│   │   │       ├── config.py
│   │   │       ├── dashboard.py
│   │   │       ├── inventory.py
│   │   │       ├── inventory_mgmt.py  # stock summary + per-product patch
│   │   │       ├── invoices.py
│   │   │       ├── products.py
│   │   │       ├── replenishment.py
│   │   │       ├── replay.py
│   │   │       ├── sales.py
│   │   │       └── users.py
│   │   ├── application/
│   │   │   └── handlers/         # Command handlers (write path)
│   │   ├── core/                 # DB, settings, security
│   │   ├── domain/
│   │   │   ├── aggregates/       # DraftSale, Product, InventoryLayer, Category
│   │   │   ├── commands/         # Command value objects
│   │   │   └── events/           # Domain event definitions
│   │   ├── infrastructure/
│   │   │   ├── event_store/      # StoredEvent model + append logic
│   │   │   ├── projectors/       # Event → read-model projectors + read entities
│   │   │   └── repositories/     # Aggregate repositories + Unit of Work
│   │   └── services/
│   │       ├── invoice_pipeline/ # pdfplumber layout + Claude Vision extraction
│   │       ├── milp_engine/      # PuLP / CBC optimisation solver
│   │       └── replay_service.py # Historical state reconstruction
│   ├── alembic/
│   │   └── versions/             # 0001 events · 0002 read entities · 0003 users
│   │                             # 0004 per-product replenishment params
│   ├── tests/
│   │   ├── test_command_handlers.py
│   │   ├── test_event_store_repository.py
│   │   ├── test_read_projectors.py
│   │   └── test_unit_of_work.py
│   ├── pytest.ini
│   └── seed.py                   # 3 users + 51-product bar menu
├── frontend/
│   └── src/
│       ├── api/                  # Axios service modules
│       ├── components/
│       │   ├── AppLayout.tsx     # Root layout — applies role-based page background
│       │   ├── InvoiceProcessor.tsx  # Shared invoice upload + AI review component
│       │   ├── NavBar.tsx        # Role-themed navbar + ROLE_THEME export
│       │   └── ReplenishmentSuggestions.tsx  # Shared MILP results panel
│       ├── pages/
│       │   ├── AdminPage.tsx
│       │   ├── AuditTrailPage.tsx
│       │   ├── DashboardPage.tsx
│       │   ├── InventoryPage.tsx # Stock table + per-product override editor
│       │   ├── InvoicesPage.tsx
│       │   ├── LoginPage.tsx
│       │   ├── POSPage.tsx
│       │   ├── ReplayPage.tsx
│       │   └── SettingsPage.tsx
│       └── store/                # Zustand auth store
├── screencaptures/               # UI screenshots referenced in this README
├── .env.example
└── docker-compose.yml
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string (`postgresql+asyncpg://...`) |
| `SECRET_KEY` | Yes | — | JWT signing secret (min 8 chars; use 32+ in production) |
| `ANTHROPIC_API_KEY` | Yes* | — | API key for Claude Vision invoice extraction (*required for invoice features) |
| `OCR_ENGINE_PATH` | Yes | — | Absolute path to the Tesseract binary |
| `SESSION_EXPIRE_SECONDS` | No | 28800 | JWT lifetime in seconds (default: 8 hours) |
| `AI_CONFIDENCE_THRESHOLD` | No | 0.65 | Minimum confidence for auto-accepting extracted invoice fields |
| `REPLENISHMENT_TARGET_DAYS` | No | 30 | Default target stock coverage horizon in days |
| `REPLENISHMENT_LEAD_TIME_DAYS` | No | 3 | Default supplier lead time in days |
| `REPLENISHMENT_WEEKLY_BUDGET` | No | 150000 | Weekly purchasing budget (HUF); enforced as a hard constraint in the MILP solver |
| `COSTING_STRATEGY` | No | FIFO | Inventory valuation method — `FIFO` or `WAC` |
| `MARGIN_TARGET` | No | 0.70 | Default portfolio margin target 0–1; used to auto-price new products on invoice approval |

All runtime parameters can also be changed live via the Settings page — changes are persisted as `SystemConfigEvent` entries and take effect on the next operation without a restart.

---

## Key Design Decisions

**Event Sourcing** — The event store is append-only at the database level. No row is ever updated or deleted. All current state is a projection of the event history, enabling deterministic replay to any point in time.

**CQRS** — Commands go through aggregate → event → projector pipelines. Queries read from denormalised read-model tables kept in sync by projectors running inside the same Unit of Work transaction. The two paths share no data access layer.

**Human-in-the-loop invoice processing** — The AI pipeline extracts and scores fields but never writes to the event store. A human manager must review and approve before any `InventoryIntakeEvent` is committed.

**Margin-based auto-pricing** — When a new product is encountered during invoice approval, a selling price is automatically derived as `unit_cost / (1 − margin_target)` using the configured margin target.

**FIFO inventory layers** — Each approved invoice line creates a separate `InventoryLayer` with its own unit cost. Stock depletion during sales works through layers in arrival order (FIFO), enabling accurate cost-of-goods calculation. WAC is also supported as a runtime-switchable alternative.

**MILP with budget ceiling** — The replenishment solver minimises total procurement cost subject to per-product coverage constraints and a global weekly budget ceiling. Since ordering zero units is always feasible, the LP is always feasible and the solver always returns `Optimal`. When the budget is binding, `budget_constrained = True` is surfaced in the UI and lower-urgency products may not reach their full target coverage horizon.

**Per-product replenishment overrides** — Products have optional `lead_time_days` and `target_coverage_days` columns. The MILP engine uses a product-level override when set, falling back to the global system config otherwise. This enables different replenishment horizons for products with different shelf lives or supplier lead times without requiring separate configuration groups.

**Shared UI components** — `InvoiceProcessor` and `ReplenishmentSuggestions` are single React components used on both the Dashboard and their dedicated pages. A `refreshKey` prop (incrementing integer) triggers a fresh API fetch without unmounting, enabling post-approval replenishment refresh signalled via an `onLoad` callback.

**Role-based theming** — The UI colour scheme changes with the authenticated role (sky blue for cashiers, emerald for managers, violet for admins), resolved at runtime from the exported `ROLE_THEME` constant in `NavBar.tsx` and applied globally by `AppLayout`.
