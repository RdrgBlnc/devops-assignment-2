# Running services with *docker run*

Run each service on its own, before Docker Compose.

Run them from the repo root.

**Apple Silicon Macs (M1 and later):** 
- The SQL Server image only exists for Intel, so the database command below has `--platform linux/amd64`.
- In Docker Desktop, turn on Settings > General > "Use Rosetta for x86_64/amd64 emulation on Apple Silicon".
- It starts slower (about a minute). The two service images build natively and need no flag.

## 1. Network and database server

First, generate the local environment and SQL Server password by running the following command from the repository root:

PowerShell and macOS / Linux:
```
uv run .\tools\make_env.py
```

Then, load the generated password into the terminal session.

PowerShell:
```
$SA = (Get-Content .env | Where-Object { $_ -match '^SA_PASSWORD=' }) -replace '^SA_PASSWORD=', ''
```

macOS / Linux:
```
export SA=$(grep '^SA_PASSWORD=' .env | cut -d '=' -f2-)
```

## 2. Network and database server

**Expect:** the network name, the SQL Server container id, 
then silence from `sqlcmd` (no output means both databases were created; 
an error message means wait longer and run it again).

PowerShell:
```
docker network create ruta7

docker run -d --name sql --network ruta7 -p 1433:1433 `
  -e ACCEPT_EULA=Y -e "MSSQL_SA_PASSWORD=$SA" `
  mcr.microsoft.com/mssql/server:2022-latest

# wait about 20 seconds, then create one empty database per service
docker exec sql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$SA" -C `
  -Q "CREATE DATABASE vehicles; CREATE DATABASE reservations;"
```

macOS / Linux:
```
docker network create ruta7

docker run -d --name sql --network ruta7 -p 1433:1433 --platform linux/amd64 \
  -e ACCEPT_EULA=Y -e 'MSSQL_SA_PASSWORD=$SA' \
  mcr.microsoft.com/mssql/server:2022-latest

# wait about 20 seconds (about a minute on Apple Silicon), then create the databases
docker exec sql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P '$SA' -C \
  -Q "CREATE DATABASE vehicles; CREATE DATABASE reservations;"
```

## 3. Build and run the vehicles service

**Expect:** the build finishes with no error, `docker run` prints a container id, 
the logs show `migration applied: 001_init.sql` and `loaded 2059 vehicles`, `/health` returns `status: ok`, 
and `/vehicles?limit=2` returns 2 vehicles with `total` 2059 (an empty reply just means it is still loading the seed: 
wait 10 seconds).

PowerShell:
```
docker build -t ruta7-vehicles services/vehicles

docker run -d --name vehicles --network ruta7 -p 8001:8000 `
  -e "DATABASE_URL=mssql+pymssql://sa:$SA@sql:1433/vehicles" `
  -e CORS_ORIGIN=http://localhost:8080 `
  ruta7-vehicles

docker logs vehicles            # "migration applied: 001_init.sql", then the seed rows
curl.exe http://localhost:8001/health
curl.exe "http://localhost:8001/vehicles?limit=2"
```

macOS / Linux:
```
docker build -t ruta7-vehicles services/vehicles

docker run -d --name vehicles --network ruta7 -p 8001:8000 \
  -e 'DATABASE_URL=mssql+pymssql://sa:$SA@sql:1433/vehicles' \
  -e CORS_ORIGIN=http://localhost:8080 \
  ruta7-vehicles

docker logs vehicles            # "migration applied: 001_init.sql", then the seed rows
curl http://localhost:8001/health
curl "http://localhost:8001/vehicles?limit=2"
```

## 4. Build and run the reservations service

**Expect:** the same as vehicles, with `loaded 100 customers` and `loaded 151 rentals` in the logs, 
`/health` returning `database: ok`, and `/customers?limit=2` returning 2 customers with `total` 100.

PowerShell:
```
docker build -t ruta7-reservations services/reservations

docker run -d --name reservations --network ruta7 -p 8002:8000 `
  -e "DATABASE_URL=mssql+pymssql://sa:$SA@sql:1433/reservations" `
  -e VEHICLES_URL=http://vehicles:8000 `
  -e CORS_ORIGIN=http://localhost:8080 `
  ruta7-reservations

docker logs reservations
curl.exe http://localhost:8002/health
curl.exe "http://localhost:8002/customers?limit=2"
```

macOS / Linux:
```
docker build -t ruta7-reservations services/reservations

docker run -d --name reservations --network ruta7 -p 8002:8000 \
  -e 'DATABASE_URL=mssql+pymssql://sa:$SA@sql:1433/reservations' \
  -e VEHICLES_URL=http://vehicles:8000 \
  -e CORS_ORIGIN=http://localhost:8080 \
  ruta7-reservations

docker logs reservations
curl http://localhost:8002/health
curl "http://localhost:8002/customers?limit=2"
```

## 5. Check the two services work together
 
PowerShell:

**Expect:** a rental with `status: pending` and `total_price` equal to 3 days times the vehicle's daily rate 
(use a real `reg_num` of an active vehicle, from `/vehicles?status=active&limit=1`).

```
$body = @{ customer_id = 1; car_reg_num = "<a reg_num from the /vehicles answer>";
           start_date = (Get-Date).AddDays(3).ToString("yyyy-MM-dd");
           end_date = (Get-Date).AddDays(6).ToString("yyyy-MM-dd") } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8002/rentals -ContentType "application/json" -Body $body
```
 
macOS / Linux (macOS `date` syntax; on Linux use `date -d '+3 days' +%F`):

**Expect:** the same rental as above, `status: pending`, 
with `total_price` equal to 3 days times the vehicle's daily rate.

```
curl -X POST http://localhost:8002/rentals -H 'Content-Type: application/json' -d "{
  \"customer_id\": 1,
  \"car_reg_num\": \"<a reg_num from the /vehicles answer>\",
  \"start_date\": \"$(date -v+3d +%F)\",
  \"end_date\": \"$(date -v+6d +%F)\"
}"
```
 
Then stop the vehicles service and repeat the same call (same commands on both systems):
 
**Expect:** the repeated `POST` fails with HTTP 503 and `vehicles_unavailable` 
(PowerShell's `Invoke-RestMethod` hides the number; `curl -i` shows it), no rental is saved, 
`/customers` still answers 200, and after `docker start` the `POST` works again.

```
docker stop vehicles
# repeat the POST /rentals above, then check the customers still load:
curl http://localhost:8002/customers?limit=1
docker start vehicles
```
 
**Expect:** `no pending migrations (1 already applied)` and no `seed: loaded` lines, 
because the data is already there and is never loaded twice.
 
```
docker restart vehicles reservations
docker logs reservations
```
 

## 6. Clean up (same on both systems)
 
**Expect:** the container names, then the network name, printed back; 
everything (including both databases) is deleted.

```
docker rm -f reservations vehicles sql
docker network rm ruta7
```
