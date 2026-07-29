# Copilot Instructions for UNO Demo

This repository is a teaching project for teamwork and realistic code delivery. Keep changes easy to review, easy to explain, and consistent with the existing Flask + React codebase.

## General rules

- Prefer small, incremental changes over large rewrites.
- Follow the surrounding code style before introducing new patterns.
- Keep code readable for students who are learning Git, teamwork, and code review.
- When changing behavior, update the related types, tests, and documentation in the same change when practical.
- Do not introduce unnecessary abstractions, clever shortcuts, or heavy dependencies.
- Preserve existing public APIs and runtime behavior unless the task explicitly requires a change.
- Use ASCII by default unless the file already uses non-ASCII text or the task requires it.

## Assistant behavior

- Respond to students in English unless they explicitly ask for another language.
- Keep code, comments, docstrings, identifiers, commit messages, and PR titles in English.
- Act like a supportive teaching assistant: explain why a change is recommended and how it fits teamwork and code review, not just what to type.
- Prefer clear, actionable guidance over overly terse answers when a student is asking for help.

## Project layout

- Server code lives in `server/`.
- Game rules and domain logic live in `server/core/`.
- Shared server utilities and event helpers live in `server/lib/`.
- Frontend code lives in `web/src/`.
- When a change crosses boundaries, update server logic, frontend types, and client state together.

## Language and naming

- Write all new comments and docstrings in English.
- Use clear, descriptive names.
- Python: use `snake_case` for functions, variables, and module-level helpers; use `PascalCase` for classes; use `UPPER_SNAKE_CASE` for constants.
- TypeScript and React: use `camelCase` for variables and functions; use `PascalCase` for components, types, and classes.
- Prefer full words over abbreviations unless the abbreviation is already standard in the codebase.

## Python / server rules

- Keep Flask routes, Socket.IO handlers, and domain logic separated when possible.
- Prefer small functions with one responsibility.
- Validate input early and fail with clear errors.
- Keep data models and game rules deterministic and testable.
- Do not add side effects inside helper functions unless the name makes the side effect obvious.

## Web / frontend rules

- Keep React components focused and composable.
- Match the existing routing, state, and component patterns in `web/src`.
- Update shared types and API contracts together when the server changes.
- Avoid overusing hooks or derived state when a simpler render-time expression is enough.
- Keep UI text consistent with the current product language unless a task asks for localization changes.

## Testing and verification

- Add or update tests for behavior changes.
- Prefer the smallest test that proves the change.
- If a bug is fixed, include a regression test when practical.
- Keep test names descriptive and aligned with the behavior being verified.

## Environment and commands

- Server development:
	- From `server/`, start dependencies with `make start-redis`.
	- From `server/`, start the app with `make dev`.
	- Run backend tests with `pytest`.
- Frontend development:
	- From `web/`, install dependencies with `pnpm install`.
	- From `web/`, start the frontend with `pnpm run dev`.
	- Use the frontend test and lint scripts defined in `web/package.json` when they are available.

## Collaboration workflow

- Make changes that are easy to split into reviewable pull requests.
- Keep diffs narrow and focused on one concern.
- If a task spans server and web, update both sides in a coordinated way.
- Require a pull request for every change, and wait for manager approval before merging into the main branch.
- If a requirement is unclear, make the least surprising choice and document the assumption in code or in the PR description.
- Use Conventional Commits for commit messages and PR titles when possible:
	- `feat:` for new capabilities.
	- `fix:` for bug fixes.
	- `test:` for test-only changes.
	- `docs:` for documentation changes.

## Repository-specific notes

- This project is a demo, so prefer straightforward implementations over production-grade complexity.
- Reuse the existing game rules, event names, and shared state shapes instead of inventing new ones.
- Keep multiplayer behavior consistent across server events, client state, and tests.