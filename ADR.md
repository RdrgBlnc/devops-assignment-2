# Architecture Decision Record - Ruta7 Car Rental Platform

## [1]. Backend framework: Flask
- Date: 23-9-2026
- Status: Decided
- Context: Needed a Python web framework for server-rendered HTML pages in a single-process app, with SQLite handled by hand instead of an ORM.
- Decision: Use Flask with Jinja2 templates.
- Alternatives considered: Django - rejected, its ORM and admin panel aren't needed here. FastAPI - rejected, it's built for JSON APIs, not HTML pages.
- Consequences: Less built-in structure to rely on, but fewer dependencies and simpler code to explain.

## [2]. Domain between Vehicle and Reservations
- Date: 29-9-2026
- Status: Decided
- Context: The two domains need to stay loosely coupled, but a rental still has to reference a real car.
- Decision: A rental stores only the car's reg_num and a price snapshot taken at booking time, instead of reading Vehicle's data live.
- Alternatives considered: querying Vehicle's table directly from Reservations - rejected, since it would couple the two domains and let price changes silently affect old rentals.
- Consequences: One extra lookup per booking, but Reservations stays the clean seam for a future service split.

## [3]. SQLite schema: natural keys, enums as text
- Date: 01-10-2026
- Status: Decided
- Context: SQLite has no enum type, and a vehicle's reg_num is already a unique real-world identifier.
- Decision: Use reg_num as the primary key directly, and store enum fields (status, fuel, type, category) as plain text validated in Python.
- Alternatives considered: adding a separate autoincrement id to vehicles - rejected as redundant since reg_num is already unique.
- Consequences: Simple, readable joins, but reg_num can't be changed later without updating a primary key.

## [4]. Testing approach: business logic and routes
- Date: 02-10-2026
- Status: Decided
- Context: Around 80% of methods are tested.
- Decision: Prioritized the rental builder validation rules and the transport logic. Tested the DB layer against a real temporary SQLite file. Vehicle builder isn't tested as it contains same logic as rental, but it will be used a lot less often (rentals are created more often than new vehicles).
- Alternatives considered: Testing all files, including routing and template - rejected as it would take a lot of time, and it is updated less frequently, so new bugs happen less often.
- Consequences: Core logic is well covered, but a routing or template bug could still slip through untested.

## [5]. Deliberately not built: password-based login
- Date: 04-10-2026
- Status: Decided
- Context: Customers needed a way to access their own rentals, but building real authentication was a disproportionate amount of work for this assignment's scope.
- Decision: Customers log in by inputting their id.
- Alternatives considered: Full authentication with hashed passwords - rejected as unnecessary complexity for a local, single-user-at-a-time demo app.
- Consequences: Anyone can act as any customer, so this is not production-safe, but it kept the customer flow simple to build, test, and demo within the time available.

## [6]. The split: vehicles and reservations services
- Date: 2026-11-18
- Status: Decided
- Context: Assignment 2 allows exactly two services, and ADR-2 already kept vehicles and reservations apart.
- Decision: Vehicles owns vehicles and the transport queue, reservations owns customers and rentals.
- Alternatives considered: A third transport service - rejected, only two containers are allowed.
- Consequences: ADR-2 held, but a rental now needs the vehicles service to be operational.

## [7]. Data and migrations: one database per service
- Date: 2026-11-20
- Status: Decided
- Context: Each service now needs its own SQL Server database, and schema changes must keep the existing data.
- Decision: Each service applies numbered SQL files at startup and records them in a `schema_migrations` table, so each file runs once.
- Alternatives considered: Alembic - rejected, a small runner of plain SQL files is simpler to explain. Recreating the schema on every boot - rejected, it deletes new created data from users.
- Consequences: The foreign key from rentals to vehicles is gone, so the car is checked over HTTP when booking. A bad migration is rolled back and fixed with a new migration, and damaged data will be restored from Azure's automatic backups.