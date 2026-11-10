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

## More checks

* **Frontend unit tests** (`npm run test:unit`): plain Node, no extra packages. They cover the money maths
  (`lib/money.ts`: sums in whole cents, running totals) and the sub-category roll-up (`lib/rollup.ts`). Put a
  `*.test.ts` beside any other pure function in `lib/`; files there that tests import must use relative
  imports ending in `.ts`.
* **Types in the backend** (`mypy app`, config `backend/mypy.ini`): installed by `requirements-dev.txt`. CI runs
  it but does not fail on it yet; run it once locally, fix what it reports, then remove `continue-on-error`
  from `.github/workflows/ci.yml`.
* **Lint rules**: ruff checks syntax and pyflakes, import order, likely bugs (bugbear), modern syntax,
  tidy comprehensions and redundant code (`backend/ruff.toml`).
* **Guards** (`backend/tests/test_guards.py`): no SQL built from strings, a search's `%` and `_` are plain
  characters, and no network code outside the local-model modules.
* **Offline proof**: `scripts/check-offline.ps1` (see `windows-setup.md`).

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

* `backend/app/routers/`: HTTP endpoints, one file per area (overview, trend, tracker, ird, savings, categories, rules, categorization, imports, history...).
* `backend/app/tuning.py`: every threshold the reports and alerts use, with `TUNE_<NAME>` overrides.
* `backend/app/services/`: the logic (categorizer, interest, ird, savings, embeddings, ...). Routers stay thin.
* `frontend/app/(app)/`: pages. `frontend/components/`: shared pieces, with `categories/`, `dashboard/`
  and `transactions/` holding parts split out of the big pages.
* `scripts/`: backup, restore, restore drill, browser tests.
