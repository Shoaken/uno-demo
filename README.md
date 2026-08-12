# UNO Demo Dependency and Framework Notes

This document keeps only shared project information: dependency baseline and framework structure.

## Python Version

- python==3.10.20

## Backend Dependency Baseline

Core server dependencies:

- flask==2.2.3
- Flask-SocketIO==5.3.3
- Flask-Cors==3.0.10
- redis==4.5.2
- gunicorn==20.1.0
- eventlet==0.30.2

Common compatibility/runtime dependencies currently used:

- Werkzeug==2.2.3
- Jinja2==3.0.3
- itsdangerous==2.0.1
- python-socketio==5.16.3
- python-engineio==4.13.3

Test dependency:

- pytest

## Frontend Dependency Baseline

Frontend dependencies currently used by the web app:

- react
- react-dom
- socket.io-client

Frontend development and test dependencies:

- @vitejs/plugin-react
- typescript
- vite
- vitest
- jsdom
- @testing-library/react

Frontend package management:

- install dependencies from `web` with `npm install`
- run the frontend with `npm run dev`
- run frontend tests with `npm test`
- build the frontend with `npm run build`

## Local verification commands

Use these commands to validate the demo-ready flow:

- Run backend tests: `pytest -q`
- Install frontend dependencies: `cd web && npm install`
- Run frontend tests: `cd web && npm test`
- Build the frontend: `cd web && npm run build`

## Demo validation summary

The project is in a presentation-ready state. The verified flow includes:

- backend service startup and health check
- frontend app startup and HTTP 200 response on the Vite dev server
- room creation and player join workflow
- ready/start progression for multiplayer game flow
- reconnect and recovery behavior after disconnects
- host transfer and the leave lifecycle
- safe handling of wild-card chosen-color plays

The critical verification commands completed successfully:

- `pytest -q` → backend regression suite passed
- `cd web && npm test` → frontend test suite passed
- `cd web && npm run build` → frontend production build passed

## Presenter handoff

Recommended live demo flow:

1. Open the frontend app in the browser.
2. Create a room from one player session.
3. Open a second browser session or tab and join the same room.
4. Mark both players as ready.
5. Start the game and play a few cards.
6. Simulate a disconnect and confirm that the reconnect messaging and recovered state are clear.
7. Show host transfer on leave or disconnect and confirm room updates are broadcast correctly.

## Demo readiness checklist

- Use the GitHub issue template at `.github/ISSUE_TEMPLATE/demo-ready-checklist.md` to track final validation and demo preparation.

## Ready-to-paste PR description

This project delivers a stable UNO demo with multiplayer room management, reconnect recovery, and clear user feedback during socket disconnects. It includes a validated room lifecycle, host handover flow, wild-card chosen-color handling, and automated regression coverage for the key demo scenarios. The frontend and backend were both verified end-to-end and the app is ready for presentation.

## Project Framework Overview

Monorepo-level layout:

- uno-main/server: Python backend (Flask + Socket.IO + Redis)
- uno-main/web: Frontend application (React + TypeScript + Vite)
- uno_demo: Project notes and architecture artifacts

Backend structure:

- app.py: HTTP and Socket.IO entrypoints
- core/uno.py: UNO domain model and game rules
- lib/state.py: game lifecycle and Redis-backed state storage
- lib/parser.py: request and response payload parsing
- lib/notification.py: game notification abstraction
- tests/: backend test cases

Frontend structure:

- src/App.tsx: main application shell and screen switching
- src/lib: API and socket helpers
- src/types.ts: shared TypeScript types
- src/main.tsx: application entry point
- src/styles.css: global styling
- src/App.test.tsx: frontend contract tests

## Notes

- This file intentionally excludes personal machine paths and local run commands.
- Runtime and startup instructions can be added later when deployment and team workflow are finalized.
- API and event details are documented in [API.md](API.md).
- Optional Redis persistence can be enabled with `UNO_USE_REDIS=1` and `UNO_REDIS_URL=...`.
