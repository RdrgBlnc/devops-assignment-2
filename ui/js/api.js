// Calls to the two services. Every function returns the JSON answer, or throws an ApiError
// with the service's own error code and message, so the pages can show what went wrong.
(function () {
  const config = Object.assign(
    { vehiclesUrl: "http://localhost:8001", reservationsUrl: "http://localhost:8002" },
    window.RUTA7_CONFIG || {}
  );

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

  async function request(service, base, path, options) {
    const { method = "GET", body, query } = options || {};
    const init = { method, headers: {} };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(base.replace(/\/$/, "") + path + queryString(query), init);
    } catch (error) {
      throw new ApiError(0, "unreachable", "The " + service + " service cannot be reached.", service);
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
