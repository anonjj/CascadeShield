import urllib.request
import urllib.error
import json
import sys

class ToxiproxyClient:
    def __init__(self, base_url="http://localhost:8474"):
        self.base_url = base_url

    def _request(self, path, method="GET", data=None):
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        req_data = json.dumps(data).encode("utf-8") if data is not None else None
        
        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status in [200, 201, 204]:
                    res_body = response.read().decode("utf-8")
                    return json.loads(res_body) if res_body else {}
                return {}
        except urllib.error.HTTPError as e:
            res_err = e.read().decode("utf-8")
            raise Exception(f"HTTP Error {e.code}: {res_err}")
        except urllib.error.URLError as e:
            print(f"Connection error to Toxiproxy at {self.base_url}: {e.reason}", file=sys.stderr)
            raise e

    def create_proxy(self, name, listen_port, upstream_host_port):
        """Creates or updates a proxy in Toxiproxy."""
        payload = {
            "name": name,
            "listen": f"0.0.0.0:{listen_port}",
            "upstream": upstream_host_port,
            "enabled": True
        }
        # Check if exists first
        try:
            self._request(f"/proxies/{name}")
            # If it exists, update it or just verify
            print(f"Proxy '{name}' already exists.")
            return
        except Exception:
            # Does not exist, create it
            print(f"Creating proxy '{name}' listening on port {listen_port} -> {upstream_host_port}")
            self._request("/proxies", method="POST", data=payload)

    def set_enabled(self, name, enabled=True):
        """Enables or disables a proxy (used to simulate complete service crashes)."""
        payload = {"enabled": enabled}
        print(f"Setting proxy '{name}' enabled={enabled}")
        self._request(f"/proxies/{name}", method="PATCH", data=payload)

    def inject_latency(self, name, delay_ms, jitter_ms=0, toxicity=1.0, clear_first=True):
        """Injects latency into a proxy's downstream path.

        Pass clear_first=False to stack this toxic on top of an existing one."""
        if clear_first:
            self.clear_toxics(name, raise_on_error=True)

        payload = {
            "name": "latency_toxic",
            "type": "latency",
            "stream": "downstream",
            "toxicity": toxicity,
            "attributes": {
                "latency": delay_ms,
                "jitter": jitter_ms
            }
        }
        print(f"Injecting latency on '{name}': {delay_ms}ms (toxicity={toxicity})")
        self._request(f"/proxies/{name}/toxics", method="POST", data=payload)

    def inject_reset_peer(self, name, timeout_ms=0, toxicity=1.0, clear_first=True):
        """Resets the TCP connection on a fraction of requests (toxicity), simulating a
        graded crash -- toxicity=1.0 resets every connection, matching a full outage.

        Pass clear_first=False to stack this toxic on top of an existing one."""
        if clear_first:
            self.clear_toxics(name, raise_on_error=True)

        payload = {
            "name": "reset_peer_toxic",
            "type": "reset_peer",
            # "upstream" (not "downstream", like inject_latency above) is deliberate,
            # not an oversight: downstream only fires once the real service's response
            # starts flowing back -- meaning the request still reaches and is processed
            # by the real service before the connection resets. upstream resets on the
            # client's outbound bytes, before the proxy ever forwards to the service,
            # matching the "instance is down" semantics of the old set_enabled(False)
            # crash path this replaced. (Verified/fixed once already: commit c827880.)
            "stream": "upstream",
            "toxicity": toxicity,
            "attributes": {
                "timeout": timeout_ms
            }
        }
        print(f"Injecting reset_peer on '{name}': timeout={timeout_ms}ms (toxicity={toxicity})")
        self._request(f"/proxies/{name}/toxics", method="POST", data=payload)

    def clear_toxics(self, name, raise_on_error=False):
        """Removes all toxics from a specific proxy.

        raise_on_error=False (default) is reset_all()'s best-effort mode: log and
        keep going, since a failure on one proxy shouldn't stop the rest of the mesh
        from being reset. inject_latency/inject_reset_peer's clear_first=True path
        passes raise_on_error=True instead -- silently continuing to layer a NEW
        toxic on top of a clear that failed risks a compound/contaminated fault,
        undetectable beyond this stderr line. run_experiment_run's existing
        try/except around inject_fault() already aborts the run correctly (logs,
        resets, returns False) once this propagates -- no new handling needed
        there, just letting the failure actually reach it."""
        try:
            # Fetch toxics from the separate toxics endpoint
            toxics_resp = self._request(f"/proxies/{name}/toxics")
            if not isinstance(toxics_resp, list):
                toxic_names = []
            else:
                toxic_names = [t.get("name") for t in toxics_resp if isinstance(t, dict)]

            for t_name in toxic_names:
                self._request(f"/proxies/{name}/toxics/{t_name}", method="DELETE")
            print(f"Cleared all toxics on '{name}'")
        except Exception as e:
            print(f"Failed to clear toxics on '{name}': {e}", file=sys.stderr)
            if raise_on_error:
                raise

    def reset_all(self):
        """Resets all proxies to healthy (enables them and clears all toxics)."""
        print("Resetting all Toxiproxy proxies...")
        try:
            self._request("/reset", method="POST")
            # Ensure all proxies are enabled
            proxies = self._request("/proxies")
            for name in proxies.keys():
                self.set_enabled(name, True)
                self.clear_toxics(name)
        except Exception as e:
            print(f"Error resetting Toxiproxy: {e}", file=sys.stderr)

    def setup_default_proxies(self):
        """Configures all standard proxies for CascadeShield."""
        # Map of proxy name -> (listen port, upstream host/port)
        # In docker, Toxiproxy container resolves container names.
        proxies_map = {
            "order-service-proxy": (8661, "order-service:8081"),
            "inventory-service-proxy": (8662, "inventory-service:8082"),
            "payment-service-proxy": (8663, "payment-service:8083"),
            "notification-service-proxy": (8664, "notification-service:8084"),
            "shared-db-service-proxy": (8665, "shared-db-service:8085")
        }
        for name, (port, upstream) in proxies_map.items():
            try:
                self.create_proxy(name, port, upstream)
            except Exception as e:
                print(f"Failed to create proxy '{name}': {e}", file=sys.stderr)

if __name__ == "__main__":
    # If run directly, reset and print version
    client = ToxiproxyClient()
    try:
        version_info = client._request("/version")
        print(f"Toxiproxy is active! Version: {version_info}")
        client.setup_default_proxies()
        client.reset_all()
        print("Toxiproxy environment has been successfully initialized!")
    except Exception as e:
        print(f"Toxiproxy initialization failed: {e}", file=sys.stderr)
