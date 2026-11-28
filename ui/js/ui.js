// Small helpers shared by all pages: building elements safely, money, messages, paging.
(function () {
  // Build an element. Text always goes in as text (never as HTML), so a vehicle called
  // "<img onerror=...>" is shown as text and cannot run anything.
  function h(tag, attrs, ...children) {
    const element = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (value === undefined || value === null || value === false) return;
      if (key === "class") element.className = value;
      else if (key === "value") element.value = value;
      else if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
      else element.setAttribute(key, value === true ? "" : value);
    });
    children.flat().forEach((child) => {
      if (child === undefined || child === null || child === false) return;
      element.append(child.nodeType ? child : document.createTextNode(String(child)));
    });
    return element;
  }

  const euro = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });
  const money = (amount) => (amount === null || amount === undefined ? "—" : euro.format(amount));
  const capitalize = (text) => (text ? text.charAt(0).toUpperCase() + text.slice(1) : "");
  const param = (name) => new URLSearchParams(window.location.search).get(name) || "";
  const today = () => new Date().toISOString().slice(0, 10);

  // -- messages ---------------------------------------------------------------------------

  function showMessage(kind, text) {
    const box = document.getElementById("message");
    if (!box) return;
    box.className = "banner banner--" + kind;
    box.textContent = text;
  }

  const showError = (error) => {
    console.error(error);
    showMessage("error", error && error.message ? error.message : "Something went wrong.");
  };
  const showOk = (text) => showMessage("ok", text);
  const clearMessage = () => {
    const box = document.getElementById("message");
    if (box) {
      box.className = "banner";
      box.textContent = "";
    }
  };

  // "Starting up" message while api.js waits for a sleeping service (see api.js). It is
  // only removed if it is still the message on screen, so it never hides an error.
  const STARTING = "starting up";
  const waitingFor = new Set();
  window.addEventListener("ruta7:waiting", (event) => {
    const { service, waiting } = event.detail;
    if (waiting) waitingFor.add(service);
    else waitingFor.delete(service);
    const box = document.getElementById("message");
    if (!box) return;
    const showing = box.classList.contains("banner--info") && box.textContent.includes(STARTING);
    if (waitingFor.size) {
      if (!box.textContent || showing) {
        const names = Array.from(waitingFor).join(" and ");
        const verb = waitingFor.size > 1 ? " services are " : " service is ";
        showMessage("info", "The " + names + verb + STARTING + " after being idle. This can take up to a minute; the page continues by itself.");
      }
    } else if (showing) {
      clearMessage();
    }
  });

  // Run a page action; show the error instead of leaving the page silently empty.
  // The previous message is cleared first, unless the action refreshes data after
  // showing a result (options.keepMessage), so a success message is not wiped at once.
  async function guarded(action, options) {
    if (!(options && options.keepMessage)) clearMessage();
    try {
      return await action();
    } catch (error) {
      showError(error);
      return undefined;
    }
  }

  // -- forms ------------------------------------------------------------------------------

  function fillSelect(select, values, options) {
    const { blank, selected, label } = options || {};
    select.replaceChildren();
    if (blank !== undefined) select.append(h("option", { value: "" }, blank));
    values.forEach((value) => {
      select.append(
        h("option", { value, selected: value === selected }, label ? label(value) : capitalize(value))
      );
    });
  }

  // Set the filter controls from the address (?status=active&...), so a filtered list can
  // be bookmarked and the browser's back button works.
  function applyQuery(form) {
    new URLSearchParams(window.location.search).forEach((value, name) => {
      const control = form.elements[name];
      if (control && "value" in control) control.value = value;
    });
  }

  function queryFrom(names) {
    const query = {};
    names.forEach((name) => {
      const value = param(name);
      if (value) query[name] = value;
    });
    return query;
  }

  // -- paging -----------------------------------------------------------------------------

  function renderPager(container, { total, limit, offset }) {
    container.replaceChildren();
    if (total <= limit) return;
    const link = (text, newOffset, enabled) => {
      if (!enabled) return h("span", { class: "muted" }, text);
      const params = new URLSearchParams(window.location.search);
      params.set("offset", newOffset);
      return h("a", { class: "link", href: "?" + params.toString() }, text);
    };
    const first = offset + 1;
    const last = Math.min(offset + limit, total);
    container.append(
      link("← Previous", Math.max(0, offset - limit), offset > 0),
      h("span", {}, first + "–" + last + " of " + total),
      link("Next →", offset + limit, offset + limit < total)
    );
  }

  const offsetParam = () => Math.max(0, parseInt(param("offset"), 10) || 0);

  // -- the signed-in customer (kept for this browser tab only) -----------------------------

  const KEY = "ruta7.customer";
  const customerSession = {
    get() {
      try {
        return JSON.parse(sessionStorage.getItem(KEY));
      } catch (error) {
        return null;
      }
    },
    set(customer) {
      try {
        sessionStorage.setItem(KEY, JSON.stringify(customer));
      } catch (error) {
        /* the page still works for this visit without storage */
      }
    },
    clear() {
      try {
        sessionStorage.removeItem(KEY);
      } catch (error) {
        /* nothing to clear */
      }
    },
    // Customer pages call this first: no customer chosen -> go to the picker.
    require() {
      const customer = customerSession.get();
      if (!customer) window.location.replace("login.html");
      return customer;
    },
  };

  window.Ruta7 = {
    h, money, capitalize, param, today, showError, showOk, showMessage, clearMessage, guarded,
    fillSelect, applyQuery, queryFrom, renderPager, offsetParam, customerSession,
  };
})();