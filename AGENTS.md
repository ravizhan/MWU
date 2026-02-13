# AGENTS.md

Guidelines for AI coding agents working in the MWU codebase.

## Project Overview

MWU is a cross-platform WebUI for MaaFramework with a modern tech stack:
- **Backend**: Python 3.12+ with FastAPI (REST API + SSE) - serves on `http://127.0.0.1:55666`
- **Frontend**: Vue 3 + NaiveUI + Vite + UnoCSS + Pinia + TypeScript
- **Updater**: Go 1.25.6 standalone binary

## Build, Lint, and Test Commands

### Python Backend
```bash
uv run main.py        # Run development server
uv sync               # Install dependencies
uv format --preview-features format  # Format code
```

### Frontend (in `front/` directory)
```bash
cd front
pnpm dev              # Development server (proxies /api to localhost:55666)
pnpm build            # Build for production (outputs to ../page/)
pnpm lint             # Lint with oxlint (auto-fix)
pnpm format           # Format with Prettier
```

### Go Updater (in `updater/` directory)
```bash
cd updater
go build -o mwu-updater   # Build
go test ./...             # Run tests
```

### Pre-commit Hooks
```bash
pre-commit install         # Install hooks
pre-commit run --all-files # Run manually
```

Hooks: `uv-lock`, `uv-format` (Python), `pnpm-format` (frontend)

## Code Style Guidelines

### Python

**Imports** (stdlib → third-party → local):
```python
import asyncio
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from models.interface import InterfaceModel
from maa_utils import MaaWorker
```

**Type Hints** (Python 3.12+ syntax):
```python
self.worker: MaaWorker | None = None  # Union with |

class DeviceModel(BaseModel):         # Pydantic for APIs
    name: str
    adb_path: str
```

**Naming**: Classes `PascalCase`, functions/variables `snake_case`, constants `UPPER_SNAKE_CASE`, private `_leading_underscore`

**API Response**: `{"status": "success" | "failed", "data"?: any, "message"?: string}`

**Async**: Use `async/await` for I/O, `asyncio.to_thread()` for blocking calls.

### TypeScript / Vue

**Imports** (external → local):
```typescript
import { defineStore } from "pinia"
import { getSettings } from "../script/api"
import type { SettingsModel } from "../types/settings"
```

**Components**: Use `<script setup lang="ts">`

**Types**: `interface` for shapes, `type` for unions:
```typescript
interface ApiResponse { status: string; message: string }
type DarkMode = "auto" | boolean
```

**Naming**: Components `PascalCase.vue`, stores `useXxxStore`, functions/variables `camelCase`

**Formatting** (Prettier): No semicolons, double quotes, 100 char width, 2-space indent

**Styling**: UnoCSS utility classes (e.g., `class="text-center bg-gray-50 dark:bg-gray-900"`)

### Go
- `camelCase` private, `PascalCase` exported
- Return errors, use `log.Printf()` for logging
- Group imports: stdlib → third-party

## Project Structure

```
MWU/
├── main.py                 # FastAPI entry point
├── maa_utils.py            # MaaWorker class (MAA integration)
├── scheduler_manager.py    # Task scheduling
├── models/                 # Pydantic models (api.py, interface.py, scheduler.py, settings.py)
├── config/                 # JSON config files
├── front/                  # Vue frontend
│   ├── src/
│   │   ├── components/     # Vue components
│   │   ├── stores/         # Pinia stores
│   │   ├── types/          # TypeScript types
│   │   ├── script/         # API utilities
│   │   ├── views/          # Page views
│   │   └── locales/        # i18n translations
│   └── package.json
├── updater/                # Go updater binary
└── page/                   # Built frontend (served by FastAPI)
```

## Coding Constraints

1. **Third-party Libraries**: Query Context7 docs (`resolve-library-id` → `query-docs`) before modifying
2. **Type Safety**: Never use `as any`, `@ts-ignore`, or `@ts-expect-error`
3. **Language**: Chinese comments and user-facing messages are acceptable
4. **Dependencies**: `uv` for Python, `pnpm` for frontend, standard `go` for Go

## API Conventions

- All responses: `{"status": "success" | "failed", "data"?: any, "message"?: string}`
- Endpoints under `/api/`
- Real-time updates via SSE at `/api/logs`
- Static files from `/assets/` and `/resource/`
