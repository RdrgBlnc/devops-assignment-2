-- Creates the two databases and one login per service, for the local SQL Server in Docker
-- Compose. It is safe to run again: nothing is dropped, and existing objects are kept.
--
-- Run with sqlcmd, passing the two service passwords as variables:
--   sqlcmd -S sql -U sa -P "$SA_PASSWORD" -C -b -i init.sql \
--          -v VEHICLES_DB_PASSWORD="..." RESERVATIONS_DB_PASSWORD="..."
--
-- Each service gets its own login that can only use its own database, so the reservations
-- service cannot read the vehicles tables even by mistake. The tables themselves come from
-- the services' own migrations, not from this file.

IF DB_ID(N'vehicles') IS NULL CREATE DATABASE vehicles;
GO
IF DB_ID(N'reservations') IS NULL CREATE DATABASE reservations;
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'vehicles_app')
    CREATE LOGIN vehicles_app WITH PASSWORD = N'$(VEHICLES_DB_PASSWORD)', CHECK_POLICY = OFF;
ELSE
    ALTER LOGIN vehicles_app WITH PASSWORD = N'$(VEHICLES_DB_PASSWORD)';
GO
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'reservations_app')
    CREATE LOGIN reservations_app WITH PASSWORD = N'$(RESERVATIONS_DB_PASSWORD)', CHECK_POLICY = OFF;
ELSE
    ALTER LOGIN reservations_app WITH PASSWORD = N'$(RESERVATIONS_DB_PASSWORD)';
GO

-- db_owner on its own database only: the service creates its tables (migrations) there.
USE vehicles;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'vehicles_app')
    CREATE USER vehicles_app FOR LOGIN vehicles_app;
GO
ALTER ROLE db_owner ADD MEMBER vehicles_app;
GO

USE reservations;
GO
IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'reservations_app')
    CREATE USER reservations_app FOR LOGIN reservations_app;
GO
ALTER ROLE db_owner ADD MEMBER reservations_app;
GO