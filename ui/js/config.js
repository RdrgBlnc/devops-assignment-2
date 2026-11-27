// Where the two services are. The pages read these two addresses and nothing else, so the
// same files work on a laptop and in Azure: the deployment replaces this file with the
// Azure addresses (the services' own settings are not in the browser).
window.RUTA7_CONFIG = {
  vehiclesUrl: "http://localhost:8001",
  reservationsUrl: "http://localhost:8002",
};
