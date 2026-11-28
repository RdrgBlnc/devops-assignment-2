# Partial failure test (Docker Compose)

Shows that each service keeps working when the other one is down, and that the one that
needs the other answers a clear 503 instead of hanging or crashing. Run from the repo root.
On macOS/Linux use `curl` instead of `curl.exe`.

## 0. Start everything

```
uv run tools/make_env.py          # once; does nothing if .env exists
docker compose up --build -d
docker compose ps
```
**Expect:** `db-init` exited (0); `sql`, `vehicles`, `reservations` and `ui` running.

```
curl.exe http://localhost:8001/health
curl.exe http://localhost:8002/health
```
**Expect:** both `"status":"ok"`.

Keep a vehicle and a rental request ready (taken while vehicles is still up):

PowerShell:
```powershell
$reg = (Invoke-RestMethod "http://localhost:8001/vehicles?status=active&limit=1").items[0].reg_num
$body = @{ customer_id = 1; car_reg_num = $reg;
           start_date = (Get-Date).AddDays(3).ToString("yyyy-MM-dd");
           end_date = (Get-Date).AddDays(5).ToString("yyyy-MM-dd") } | ConvertTo-Json
$body | Set-Content body.json
```
macOS / Linux:
```bash
reg=$(curl -s "http://localhost:8001/vehicles?status=active&limit=1" | uv run python -c "import sys,json;print(json.load(sys.stdin)['items'][0]['reg_num'])")
printf '{"customer_id":1,"car_reg_num":"%s","start_date":"%s","end_date":"%s"}' "$reg" "$(date -v+3d +%F)" "$(date -v+5d +%F)" > body.json
```

## 1. Vehicles down

```
docker compose stop vehicles
curl.exe http://localhost:8002/health
curl.exe "http://localhost:8002/customers?limit=1"
curl.exe -i -X POST http://localhost:8002/rentals -H "Content-Type: application/json" -d "@body.json"
docker compose logs reservations --tail 5
```
**Expect:** reservations `/health` is `ok` and `/customers` answers 200 (it does not need
vehicles); the `POST` answers `HTTP/1.1 503` with `"error":"vehicles_unavailable"` at once,
and no rental is created; the log shows `vehicles service not reachable` and
`POST /rentals -> 503`.

In the browser (http://localhost:8080):
- Enterprise dashboard: "starting up" message for about 10 s, then the three vehicle numbers
  show `unavailable` with a red message, while **Active rentals** still shows its number.
- Customer dashboard and Customer records: load normally.
- Browse vehicles: after about 10 s, "The vehicles service cannot be reached…".

```
docker compose start vehicles
```
**Expect:** the same `POST` now answers 201 and the pages load again, without restarting
reservations.

## 2. Reservations down

```
docker compose stop reservations
curl.exe http://localhost:8001/health
curl.exe "http://localhost:8001/vehicles?limit=1"
curl.exe http://localhost:8001/transport/queue
```
**Expect:** all three answer 200: vehicles does not depend on reservations.

In the browser:
- Enterprise dashboard: the vehicle numbers load; **Active rentals** shows `unavailable`.
- Vehicle directory, Add vehicle and Transport: work normally.
- Customer login: after about 10 s, "The reservations service cannot be reached…".

```
docker compose start reservations
```
**Expect:** everything works again.

## 3. Database down (optional)

```
docker compose stop sql
curl.exe http://localhost:8001/health
docker compose start sql
```
**Expect:** `/health` answers 503 `"database":"down"` after about 20 s (each request waits up
to `DB_REQUEST_WAIT_S` for the database), and the services do not crash; once `sql` is back
(about 20 s), `/health` is `ok` again without restarting them.

## 4. Clean up

```
del body.json                     # macOS/Linux: rm body.json
docker compose down               # add -v to also delete the database volume
```

Save the terminal output and a screenshot of each browser state for the report.