-- vehicles service, initial schema.
-- Enums (type, category, fuel, ...) are stored as text and validated in Python (ADR-3).

CREATE TABLE vehicles (
    reg_num           NVARCHAR(32)  NOT NULL PRIMARY KEY,   -- natural key (ADR-3)
    type              NVARCHAR(10)  NOT NULL,
    brand             NVARCHAR(50)  NOT NULL,
    model             NVARCHAR(100) NOT NULL,
    category          NVARCHAR(10)  NOT NULL,
    daily_rate        DECIMAL(10,2) NOT NULL,
    seat_num          INT           NOT NULL,
    plate             NVARCHAR(16)  NOT NULL UNIQUE,
    color             NVARCHAR(30)  NULL,
    fuel              NVARCHAR(10)  NOT NULL,
    transmission      NVARCHAR(10)  NOT NULL,
    km                INT           NOT NULL,
    status            NVARCHAR(12)  NOT NULL,
    location          NVARCHAR(12)  NOT NULL,
    manufacture_date  DATE          NOT NULL,
    registration_date DATE          NOT NULL
);
GO

CREATE INDEX ix_vehicles_status_location ON vehicles (status, location);
GO

-- Vehicles waiting for a truck or ship. Kept in the database, not in memory,
-- so the queue survives the container scaling to zero.
CREATE TABLE transport_queue (
    id                INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    reg_num           NVARCHAR(32)  NOT NULL REFERENCES vehicles (reg_num),
    origin            NVARCHAR(12)  NOT NULL,   -- city the current leg leaves from
    destination       NVARCHAR(12)  NOT NULL,   -- city the current leg arrives at
    mode              NVARCHAR(10)  NOT NULL,   -- 'truck' or 'ship'
    final_destination NVARCHAR(12)  NOT NULL,   -- where the whole journey ends
    enqueued_at       DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_transport_queue_vehicle UNIQUE (reg_num)   -- a vehicle waits in one queue at a time
);
GO

CREATE INDEX ix_transport_queue_leg ON transport_queue (origin, destination, mode);
GO

-- One row that GET /health updates and reads back, to prove the database is writable.
CREATE TABLE service_health (
    id         INT       NOT NULL PRIMARY KEY,
    checked_at DATETIME2 NULL
);
GO

INSERT INTO service_health (id, checked_at) VALUES (1, SYSUTCDATETIME());
GO