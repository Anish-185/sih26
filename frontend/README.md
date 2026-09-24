# MetrIQ — Frontend

React + TypeScript + Vite + Tailwind CSS v4. The UI for MetrIQ, the
evidence-backed assistant for Indian Standards & BIS services.

## Run

```bash
# 1. start the backend (from ../backend)
../backend/.venv/bin/uvicorn app.main:app --port 8000

# 2. start the frontend
npm install
npm run dev            # http://localhost:5173
```

The dev server proxies `/api/*` → `http://127.0.0.1:8000/*` (see `vite.config.ts`,
override with `VITE_BACKEND_ORIGIN`). For a production build set `VITE_API_BASE`
to the backend origin.

```bash
npm run build          # tsc -b && vite build  → dist/
npm run typecheck      # tsc -b --noEmit
npm run preview        # serve dist/ on :4173
```

## What talks to the backend

| Screen | Endpoint | Live? |
|---|---|---|
| Inspection · OCR + declarations + product + standard + compliance | `POST /inspection/analyze` | ✅ real |
| Inspection · evidence graph | `POST /evidence-graph` | ✅ real |
| History · saved inspections + PDF report | `/inspections*` | ✅ real (PostgreSQL) |
| Standards | `POST /product-standard` | ✅ real |
| Certification | `POST /certification-guidance` | ✅ real (local LLM) |
| Laboratories | `POST /laboratory-search` | ✅ real (`explain=false` by default) |
| Hallmarking / HUID | `POST /ask` | ✅ real (local LLM) |
| Header status dot | `GET /health` | ✅ real |
| Inspection · Legal Metrology PASS/FAIL | `POST /inspection/analyze` | ✅ real (verified requirements only) |
| Copilot (optional explanations) | `POST /copilot/explain` | ✅ real (OpenRouter, server-side key) |

Nothing in the UI runs on placeholder data. The deterministic rules cover only the
requirements MetrIQ has verified, so many inspections end in `REVIEW` — that is
reported honestly, with every reason listed. There is no human review workflow:
MetrIQ shows the system result, the evidence graph behind it, and what it could
not establish.

## Structure

```
src/
  main.tsx              routes
  index.css             design tokens (@theme) + base layer
  lib/
    api.ts              typed backend client (contracts mirror backend/app/api.py)
    hooks.ts            useAsyncTask / useOnMount
    format.ts, cn.ts    helpers
  components/
    ui.tsx              design-system primitives (Button, Panel, StatusBadge, …)
    layout.tsx          AppLayout, TopNav, HealthStatus, SystemLayerFooter
    Dropzone.tsx        structured upload region
    GroundedAnswer.tsx  shared answer/evidence/sources renderer
  features/
    DashboardView, StandardsView, CertificationView, LaboratoriesView,
    HallmarkingView, HistoryView, RecordView, CopilotPanel, NotFoundView
    inspection/InspectionView, inspection/ImageInspector
  components/
    EvidenceGraph.tsx        read-only evidence graph (layers, node detail, relationships)
    EvidenceGraphSection.tsx loads the graph for what is on screen
    ProductIntelligence.tsx  the canonical product context, compactly
```
