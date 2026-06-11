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

    def inject_latency(self, name, delay_ms, jitter_ms=0, toxicity=1.0):
        """Injects latency into a proxy's downstream path."""
        # Clean existing toxics first
        self.clear_toxics(name)
        
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

    def inject_bandwidth_limit(self, name, rate_kbps, toxicity=1.0):
        """Limits bandwidth to simulate throttling."""
        self.clear_toxics(name)
        
        # Toxiproxy expects rate in KB/s
        payload = {
            "name": "bandwidth_toxic",
            "type": "bandwidth",
            "stream": "downstream",
            "toxicity": toxicity,
            "attributes": {
                "rate": rate_kbps
            }
        }
        print(f"Injecting bandwidth limit on '{name}': {rate_kbps} KB/s (toxicity={toxicity})")
        self._request(f"/proxies/{name}/toxics", method="POST", data=payload)

    def clear_toxics(self, name):
        """Removes all toxics from a specific proxy."""
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
