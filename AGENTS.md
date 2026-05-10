# AGENTS.md

## Repo shape
- Frontend: Vite + React in `src/`
- Python tooling: root `.py` files plus `aws/`
- Keep generated/build output out of version control

## Working rules
- Prefer small, targeted changes.
- Do not edit `node_modules/`, `dist/`, or Python cache/build artifacts.
- Preserve existing style; avoid broad refactors unless asked.
- Update docs when behavior or setup changes.

## Common checks
- Frontend: `npm run build`
- Python: use the repo's Python toolchain if you touch `.py` files

## Notes
- If you add new app behavior, verify both the UI and any matching Python helpers.
