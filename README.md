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

- src/pages: route-level pages (home, play, won)
- src/components: reusable UI components
- src/lib: API, socket, and client-side state helpers
- src/types: shared TypeScript types

## Notes

- This file intentionally excludes personal machine paths and local run commands.
- Runtime and startup instructions can be added later when deployment and team workflow are finalized.
