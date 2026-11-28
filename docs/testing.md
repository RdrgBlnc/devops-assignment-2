# Tests and coverage

Each service has its own tests in `services/<service>/tests/` and is measured on its own
code (`app/`). A run fails if coverage is below **70%** (`.coveragerc`, `fail_under = 70`);
CI runs the same command.

## Commands

Install the test tools once (repo root):

```
uv pip install -r services/vehicles/requirements-dev.txt -r services/reservations/requirements-dev.txt
```

Run one service's tests with coverage (from its folder):

```
cd services/vehicles          # or services/reservations
uv run pytest --cov --cov-report=term-missing
```

The database tests (`test_repository.py`) need a SQL Server. Without
`TEST_SQLSERVER_URL` they are skipped and everything else still runs. To include them,
start the compose database and point the tests at it (PowerShell; the password is
`SA_PASSWORD` from your `.env`):

```
docker compose up -d sql
$env:TEST_SQLSERVER_URL = "mssql+pymssql://sa:<SA_PASSWORD>@localhost:1433/master"
uv run pytest --cov --cov-report=term-missing
```

## What is tested

| File                                          | Vehicles                                                      | Reservations                                                                                |
|-----------------------------------------------|---------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| `test_routes.py`                              | every endpoint, its errors, CORS, logs (in-memory repository) | same, with a fake vehicles client                                                           |
| `test_vehicles_integration.py`                | –                                                             | booking over real HTTP against a stand-in vehicles service: timeout, 500, down, bad answers |
| `test_repository.py`                          | every query against real SQL Server                           | same                                                                                        |
| `test_transport.py`                           | Factory Method, routes, persisted queue                       | –                                                                                           |
| `test_vehicle_builder.py` / `test_rentals.py` | VehicleBuilder rules                                          | RentalBuilder and status rules                                                              |
| `test_db.py`                                  | URL parsing, waiting for a paused database                    | same                                                                                        |
| `test_migrate.py`                             | run once, edits refused, failures roll back                   | same                                                                                        |
| `test_seed.py`                                | load once, typed, all or nothing                              | same, ids kept                                                                              |
| `test_config_startup.py`                      | settings, start-up migrate and seed                           | same                                                                                        |
| `test_service_boundary.py`                    | –                                                             | no access to the vehicles database                                                          |

## Results

Without the database tests (`TEST_SQLSERVER_URL` not set), 28 Nov 2026:

| Service      | Tests                  | Coverage of `app/` |
|--------------|------------------------|--------------------|
| vehicles     | 217 passed, 36 skipped | 90.60%             |
| reservations | 194 passed, 27 skipped | 88.54%             |

The only code left uncovered without a database is `app/repository.py` (the SQL), which
`test_repository.py` covers when SQL Server is available. With the database tests:

| Service      | Tests      | Coverage of `app/` |
|--------------|------------|--------------------|
| vehicles     | 253 passed | 98.67%             |
| reservations | 221 passed | 98.36%             |