# Repository Guidelines

## Project Structure & Module Organization
This repository now contains both implementation code and specification documents:

- `backend/app/`: FastAPI app, SQLAlchemy models, sync service, and style rotation calculation logic.
- `backend/tests/`: `unittest` coverage for API behavior and the golden sample.
- `frontend/src/`: Vue 3 single-page app with ECharts rendering.
- `README.md`: setup and run instructions.
- `STYLE_ROTATION_REWRITE_SPEC.md`: source of truth for API design, data model, and pandas calculation order.
- `STYLE_ROTATION_GOLDEN_TEST.md`: deterministic validation sample for signals, slicing order, and NAV rebasing.

Keep new modules inside these roots instead of creating extra top-level app folders.

## Build, Test, and Development Commands
Use the existing project commands:

- `uvicorn backend.app.main:app --reload`: run the backend locally.
- `python -m unittest discover -s backend/tests -v`: run backend tests, including the golden sample.
- `cd frontend && npm run dev`: start the frontend dev server.
- `cd frontend && npm run build`: build the Vue app for production.

Use `rg --files` and `git diff --stat` for fast repository inspection before commit.

## Coding Style & Naming Conventions
Python code should follow straightforward SQLAlchemy and pandas patterns, with 4-space indentation and explicit naming. Vue code uses the Composition API in `script setup`, and frontend state should stay local unless there is a clear reason to extract it.

Match the repository’s existing conventions:

- Use Chinese for explanatory prose unless a section is intentionally English.
- Keep API paths, JSON fields, and query parameters in English `snake_case`, for example `left_symbol` and `quantile_window_min`.
- Prefer concrete examples over abstract descriptions.
- Keep response payloads aligned with the documented `meta`, `series`, `summary`, and `signals` contract.

## Testing Guidelines
Treat `STYLE_ROTATION_GOLDEN_TEST.md` as the acceptance test for any future implementation. A valid backend must reproduce the documented `series`, `summary`, and `signals` values exactly for the sample input.

If you change calculation rules, update the code, both spec documents, and the matching `backend/tests/` cases together. Do not change one without checking the others for drift.

## Commit & Pull Request Guidelines
Git history currently contains only `Initial commit`, so no mature convention exists yet. Use short imperative commit messages such as:

- `docs: clarify dynamic quantile rules`
- `spec: align signal filtering with golden test`

PRs should include a brief summary, the affected document paths, and a note confirming whether the golden test document also required updates. Include sample payload diffs when API contracts change.

## Spec Consistency Rules
Do not silently change calculation order, default parameters, or response fields. Any edit affecting `GET /api/style-rotation` must preserve consistency across examples, pseudocode, and acceptance outputs.
