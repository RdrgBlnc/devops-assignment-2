-- reservations service, initial schema.

CREATE TABLE customers (
    id       INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    name     NVARCHAR(50)  NOT NULL,
    surname  NVARCHAR(50)  NOT NULL,
    email    NVARCHAR(100) NOT NULL UNIQUE,
    location NVARCHAR(12)  NOT NULL
);
GO

CREATE TABLE rentals (
    id          INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    customer_id INT           NOT NULL REFERENCES customers (id),
    -- The car lives in the vehicles service's database, so this is a plain value,
    -- not a foreign key. The booking code checks it over HTTP instead (ADR-7).
    car_reg_num NVARCHAR(32)  NOT NULL,
    start_date  DATE          NOT NULL,
    end_date    DATE          NOT NULL,
    total_price DECIMAL(10,2) NOT NULL,   -- days x daily_rate, fixed at booking time (ADR-2)
    status      NVARCHAR(12)  NOT NULL,
    CONSTRAINT ck_rentals_dates CHECK (end_date > start_date)
);
GO

CREATE INDEX ix_rentals_customer ON rentals (customer_id);
GO

CREATE INDEX ix_rentals_car_dates ON rentals (car_reg_num, start_date, end_date);
GO

-- One row that GET /health updates and reads back, to prove the database is writable.
CREATE TABLE service_health (
    id         INT       NOT NULL PRIMARY KEY,
    checked_at DATETIME2 NULL
);
GO

INSERT INTO service_health (id, checked_at) VALUES (1, SYSUTCDATETIME());
GO