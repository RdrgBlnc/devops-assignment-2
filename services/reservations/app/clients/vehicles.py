import logging
from urllib.parse import quote

import requests

log = logging.getLogger("vehicles_client")


class VehiclesUnavailable(Exception):
    """The vehicles service did not give a usable answer (down, slow or broken)."""


class VehiclesClient:
    """Asks the vehicles service about vehicles over HTTP.

    This is the only place reservations talks to the vehicles service. It never
    waits longer than timeout_s, and every failure becomes VehiclesUnavailable so
    the caller can answer 503 instead of hanging or crashing.
    """

    def __init__(self, base_url, timeout_s, session=None):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.session = session or requests.Session()

    def get_vehicle(self, reg_num):
        """The vehicle as a dict, or None if the vehicles service has no such vehicle."""
        url = f"{self.base_url}/vehicles/{quote(reg_num, safe='')}"
        try:
            response = self.session.get(url, timeout=self.timeout_s)
        except requests.ConnectTimeout:
            # nothing accepted the connection in time: on Windows a closed port looks like
            # this instead of an immediate "connection refused"
            log.warning("vehicles service not reachable within %ss: GET %s", self.timeout_s, url)
            raise VehiclesUnavailable(f"not reachable within {self.timeout_s}s")
        except requests.Timeout:
            log.warning("vehicles service timed out after %ss: GET %s", self.timeout_s, url)
            raise VehiclesUnavailable(f"timed out after {self.timeout_s}s")
        except requests.RequestException as error:
            log.warning("vehicles service not reachable: GET %s: %s", url, error)
            raise VehiclesUnavailable("not reachable")

        if response.status_code == 404:
            return None
        if response.status_code != 200:
            log.warning("vehicles service answered %s: GET %s", response.status_code, url)
            raise VehiclesUnavailable(f"answered {response.status_code}")
        try:
            vehicle = response.json()
            vehicle["status"], vehicle["daily_rate"]  # the two fields reservations relies on
        except (ValueError, KeyError, TypeError):
            log.warning("vehicles service sent an unexpected body: GET %s", url)
            raise VehiclesUnavailable("sent an unexpected answer")
        return vehicle