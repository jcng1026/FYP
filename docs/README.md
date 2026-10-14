# English Grading System — Stage 1 Prototype

A local Windows desktop prototype for an English paper grading/revision system.
This is **Stage 1**: project foundation only.

## What this prototype currently does

- Provides a Python project structure (`app/database`, `app/models`, `app/services`, `app/ui`, `app/utils`, `tests`).
- Creates and manages a local SQLite database at `data/app.db` (the `data/` folder is created automatically if missing).
- Defines a `users` table with `user_id`, `username`, `password_hash`, `full_name`, `role`, `created_at`.
- Hashes all passwords with `bcrypt` before storing them — passwords are never stored in plain text.
- Seeds a single default **Admin** account (`full_name` "System Developer") on startup, without duplicating it on subsequent runs.
- Shows a PySide6 login window with username/password fields.
- Routes a successful login to one of three dashboards based on role:
  - `admin` → Admin Dashboard
  - `teacher` → Teacher Dashboard
  - `student` → Student Dashboard
- Shows a clear error message on failed login.
- Supports three roles: `admin`, `teacher`, `student`.

## What this prototype does NOT do yet

- No OCR
- No preprocessing of scanned papers
- No template editor
- No marking/grading logic
- No Excel export
- No Kertas 2 support
- No packaging, deployment, or `.exe` build
- Dashboards are placeholders only (no real functionality behind them yet)
- No account creation/management UI (accounts are only seeded via code for now)

## How to install dependencies

From the `english_grading_system/` folder:

```
pip install -r requirements.txt
```

That is everything the application needs. It starts, marks, reviews, finalises
and publishes results with no AI component installed.

### Optional AI components

```
pip install -r requirements-ai.txt
```

These enable handwriting extraction, Core AI 1 Kertas 2 draft scoring and
Core AI 2 answer-region proposals. They are large and entirely optional. When
one is missing the application reports the limitation at startup and on the
AI Models page, and every manual workflow continues to work unchanged.

## How to run the app

From the `english_grading_system/` folder:

```
python main.py
```

On first run, this creates `data/app.db` (if it doesn't already exist) and seeds the default developer account described below.

## Default developer login

```
username: developer
password: developer123
```

Use these credentials to log in as the Admin role and reach the Admin Dashboard.

## How to run tests

From the `english_grading_system/` folder:

```
pytest
```

Tests cover:
- Password hashing never stores the plain-text password
- Correct password validates successfully
- Wrong password fails validation
- The default developer account seeds once and is not duplicated on repeat runs

## Important note

This is a **local-only prototype** for FYP development purposes. It is not packaged, not deployed, and not intended for production or multi-user use in its current state.
