# Development, testing and CI

## Everyday checks

```
cd backend
venv/Scripts/python.exe -m pytest -q          # about 510 tests, SQLite, synthetic PDFs only
venv/Scripts/ruff check .                     # lint (config: backend/ruff.toml)

cd ../frontend
node_modules/.bin/tsc --noEmit                # types
npm run lint                                  # ESLint (config: eslint.config.mjs)
npx next build                                # production build
```

Ruff is deliberately minimal at first (syntax errors and pyflakes: unused imports and names). Run
`ruff check --fix .` to remove unused imports, then widen `select` in `backend/ruff.toml` later. The
ESLint config turns the strictest new React rules into warnings, because this code loads data in
effects on purpose; errors still fail.

One-time setup for the new tooling (needs the internet once):

```
cd backend;  venv/Scripts/pip install -r requirements-dev.txt
cd ../frontend; npm install --save-dev eslint@9 eslint-config-next@16.4.4 @playwright/test
npx playwright install chromium
```

The `lint` and `test:e2e` scripts are already in `package.json`, but the packages are NOT listed
there until you run the `npm install --save-dev` line: that keeps `package.json` and
`package-lock.json` in step (the Docker build uses `npm ci`, which fails when they differ). Commit
both files afterwards. CI also uses `npm ci`, so its lint step works only after that commit.

## Browser smoke tests (Playwright)

```
.\scripts\e2e.ps1
```

Starts a SEPARATE copy of the app (project `lanka-e2e`, its own database, port 3100, AI off), runs the
tests in `frontend/e2e/`, and removes the copy. Your real data is never touched. The tests create an
account, upload an invented statement (`frontend/e2e/fixtures/synthetic-statement.pdf`, made by
`backend/tests/make_e2e_fixture.py`), look at the Transactions page, walk the three Reports tabs, add
and rename a category, and sign out. On a failure open `frontend/playwright-report/index.html` for
screenshots and traces. They are smoke tests: they check that pages load and the main flows work, not
every figure (the backend suite does that).

## Continuous integration

`.github/workflows/ci.yml` runs on every push: the backend job (ruff, pytest on Python 3.12) and the
frontend job (`npm ci`, typecheck, lint, build). It does not run the browser tests (they need Docker);
run `scripts/e2e.ps1` locally before a release.

## Layout

* `backend/app/routers/`: HTTP endpoints, one file per area (overview, trend, tracker, ird, savings...).
* `backend/app/services/`: the logic (categorizer, interest, ird, savings, embeddings, ...). Routers stay thin.
* `frontend/app/(app)/`: pages. `frontend/components/`: shared pieces, with `categories/`, `dashboard/`
  and `transactions/` holding parts split out of the big pages.
* `scripts/`: backup, restore, restore drill, browser tests.
