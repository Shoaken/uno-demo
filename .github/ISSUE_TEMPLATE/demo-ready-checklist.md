---
name: Demo Ready Checklist
about: Validate the UNO demo for stable presentation and final review.
title: Demo readiness validation
labels: chore
assignees: ''
---

## Demo Ready Checklist

Status: Completed for the current presentation-ready state.

### 1. End-to-end verification
- [x] Start the backend service and confirm it launches successfully
- [x] Start the frontend app and confirm the UI loads
- [x] Create a room in the browser
- [x] Join the room with a second player
- [x] Mark both players as ready
- [x] Start the game
- [x] Play cards normally through a few turns
- [x] Simulate a disconnect and reconnect
- [x] Confirm session recovery and game state restoration
- [x] Leave the room cleanly

### 2. Critical regression coverage
- [x] Verify reconnect restores the correct state after disconnect
- [x] Verify invalid reconnect token returns an error
- [x] Verify host leave transfers host correctly
- [x] Verify wild card play and chosen-color flow completes correctly

### 3. Frontend stability & user experience
- [x] Show clear connection state (online / offline / reconnecting)
- [x] Display a clear disconnect notification
- [x] Display a clear reconnect success notification
- [x] Prevent state flashes or resets during view transitions
- [x] Use consistent error messaging and loading indicators

### 4. Documentation and PR readiness
- [x] Update README or docs with demo startup steps
- [x] Add demo operation steps for a presenter or reviewer
- [x] Confirm PR description matches actual work
- [x] Attach screenshots or notes that support the demo flow

### Verified commands
- Backend regression tests: `pytest -q`
- Frontend tests: `cd web && npm test`
- Frontend production build: `cd web && npm run build`
- Live app smoke check: backend health and room lifecycle were exercised successfully

### Demo summary
This demo is ready for presentation. The app includes room creation, multiplayer join flow, ready/start progression, reconnect recovery, host handover, and clean leave handling. The backend and frontend were both validated together and the critical game-state transitions are covered by automated regression tests.
