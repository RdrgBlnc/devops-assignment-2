// Calls to the two services. Every function returns the JSON answer, or throws an ApiError
// with the service's own error code and message, so the pages can show what went wrong.
(function () {
  // The addresses come only from js/config.js; there is no fallback here, so a page never
  // talks to a wrong service by accident when that file is missing.
  const config = window.RUTA7_CONFIG || {};
  const missing = ["vehiclesUrl", "reservationsUrl"].filter((key) => !config[key]);

  class ApiError extends Error {
    constructor(status, code, message, service) {
      super(message);
      this.name = "ApiError";
      this.status = status; // HTTP status, or 0 when the service could not be reached
      this.code = code;     // e.g. "vehicle_not_found", "database_unavailable"
      this.service = service;
    }
  }

  function queryString(query) {
    const params = new URLSearchParams();
    Object.entries(query || {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") params.set(key, value);
    });
    const text = params.toString();
    return text ? "?" + text : "";
  }

  // -- cold starts ---------------------------------------------------------------------------
  // In Azure both services and their databases sleep when nobody uses them. The first
  // request then waits while a container starts (the browser cannot connect, or gets a
  // 502/503/504) or while the database wakes (the service answers 503 database_unavailable).
  // Those answers are retried for up to RETRY_TOTAL_MS, and the page shows a "starting up"
  // message meanwhile instead of an error.
  const retry = Object.assign({ totalMs: 90000, firstDelayMs: 1000, maxDelayMs: 8000, slowMs: 2000 }, config.retry || {});

  // Safe to send again: reads always; changes only when the service said its database was
  // not reachable, because then it stopped before saving anything. A change that failed to
  // connect is never resent, as it may have been saved before the connection dropped.
  function shouldRetry(error, method) {
    if (error.code === "database_unavailable") return true;
    if (method !== "GET") return false;
    return error.status === 0 || error.status === 502 || error.status === 503 || error.status === 504;
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const announce = (service, waiting) =>
    window.dispatchEvent(new CustomEvent("ruta7:waiting", { detail: { service, waiting } }));

  async function sendOnce(service, url, init) {
    let response;
    try {
      response = await fetch(url, init);
    } catch (error) {
      // fetch gives no details here: the service may be stopped, still starting, or not
      // allowing this page's address (CORS), and the browser does not say which.
      throw new ApiError(0, "unreachable",
        "The " + service + " service cannot be reached. It may be stopped or still starting; try again in a moment.",
        service);
    }
    let data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    if (!response.ok) {
      const code = data && data.error ? data.error : "http_" + response.status;
      const message = data && data.message ? data.message : "The " + service + " service answered " + response.status + ".";
      throw new ApiError(response.status, code, message, service);
    }
    return data;
  }

  async function request(service, base, path, options) {
    if (missing.length) {
      throw new ApiError(0, "not_configured", "js/config.js does not set " + missing.join(" and ") + ".", service);
    }
    const { method = "GET", body, query } = options || {};
    const init = { method, headers: {} };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const url = base.replace(/\/$/, "") + path + queryString(query);

    const started = Date.now();
    let delay = retry.firstDelayMs;
    let waiting = false;
    // a first answer that is merely slow (a container starting) also shows the message
    const slowTimer = setTimeout(() => { waiting = true; announce(service, true); }, retry.slowMs);
    try {
      for (;;) {
        try {
          return await sendOnce(service, url, init);
        } catch (error) {
          const left = retry.totalMs - (Date.now() - started);
          if (!(error instanceof ApiError) || !shouldRetry(error, method) || left <= 0) throw error;
          if (!waiting) { waiting = true; announce(service, true); }
          await sleep(Math.min(delay, left));
          delay = Math.min(delay * 2, retry.maxDelayMs);
        }
      }
    } finally {
      clearTimeout(slowTimer);
      if (waiting) announce(service, false);
    }
  }

  const vehicleCall = (path, options) => request("vehicles", config.vehiclesUrl, path, options);
  const reservationCall = (path, options) => request("reservations", config.reservationsUrl, path, options);
  const id = (value) => encodeURIComponent(value);

  window.Ruta7Api = {
    ApiError,
    vehicles: {
      meta: () => vehicleCall("/meta"),
      stats: () => vehicleCall("/stats"),
      list: (query) => vehicleCall("/vehicles", { query }),
      get: (regNum) => vehicleCall("/vehicles/" + id(regNum)),
      create: (body) => vehicleCall("/vehicles", { method: "POST", body }),
      update: (regNum, body) => vehicleCall("/vehicles/" + id(regNum), { method: "PATCH", body }),
      requestTransport: (body) => vehicleCall("/transport", { method: "POST", body }),
      transportQueue: () => vehicleCall("/transport/queue"),
    },
    reservations: {
      meta: () => reservationCall("/meta"),
      stats: () => reservationCall("/stats"),
      customers: (query) => reservationCall("/customers", { query }),
      customer: (customerId) => reservationCall("/customers/" + id(customerId)),
      rentals: (query) => reservationCall("/rentals", { query }),
      rental: (rentalId) => reservationCall("/rentals/" + id(rentalId)),
      createRental: (body) => reservationCall("/rentals", { method: "POST", body }),
      updateRental: (rentalId, body) =>
        reservationCall("/rentals/" + id(rentalId), { method: "PATCH", body }),
      cancelRental: (rentalId, customerId) =>
        reservationCall("/rentals/" + id(rentalId) + "/cancel", {
          method: "POST",
          body: { customer_id: customerId },
        }),
    },
  };
})();