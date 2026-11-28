// Where the two services are. The pages read these two addresses and nothing else, so the
// same files work on a laptop and in Azure: the deployment replaces this file with the
// Azure addresses (tools/write_ui_config.py).
window.RUTA7_CONFIG = {
  vehiclesUrl: "http://localhost:8001",
  reservationsUrl: "http://localhost:8002",
  // Locally nothing sleeps, so a stopped service is reported after 10 s instead of the
  // 90 s the pages wait in Azure for a container or database to wake up.
  retry: { totalMs: 10000 },
};