import atexit
import logging
import requests
from google.cloud import compute_v1
from google.oauth2 import service_account
from google.api_core.exceptions import NotFound

# --- CONFIGURATION ---
PROJECT_ID = "immofinder-438008" 
KEY_PATH = "immofinder-438008-411bf1440a6c.json" 
FIREWALL_RULE_NAME = "allow-dynamic-proxy-access"
PROXY_PORT = 8888

logger = logging.getLogger("ProxyManager")

class FirewallManager:
    def __init__(self):
        try:
            self.credentials = service_account.Credentials.from_service_account_file(KEY_PATH)
            self.firewall_client = compute_v1.FirewallsClient(credentials=self.credentials)
            self._authorized = False # Track state
        except Exception as e:
            logger.error(f"Failed to initialize GCP credentials: {e}")
            raise

    def get_my_public_ip(self) -> str:
        try:
            return requests.get("https://api.ipify.org", timeout=5).text.strip()
        except Exception as e:
            logger.error(f"Could not determine public IP: {e}")
            raise

    def authorize_current_ip(self):
        """Adds current IP and automatically registers cleanup on exit."""
        if self._authorized:
            return

        my_ip = self.get_my_public_ip()
        logger.info(f"Authorizing IP: {my_ip}...")
        
        try:
            self._add_ip_to_rule(my_ip)
            self._authorized = True
            
            # 3. Register cleanup internally. 
            # The script using this class doesn't need to do anything.
            atexit.register(self.revoke_current_ip)
            
            logger.info(f"✅ IP {my_ip} authorized. Auto-cleanup registered.")
        except Exception as e:
            logger.error(f"Failed to authorize IP: {e}")
            raise

    def revoke_current_ip(self):
        """Removes the current public IP from the firewall allow list."""
        if not self._authorized:
            return

        my_ip = self.get_my_public_ip()
        logger.info(f"Revoking IP: {my_ip}...")

        try:
            self._remove_ip_from_rule(my_ip)
            self._authorized = False
            logger.info(f"🚫 IP {my_ip} revoked.")
        except Exception as e:
            logger.error(f"Failed to revoke IP during cleanup: {e}")

    # --- Internal Helpers ---

    def _get_existing_rule(self):
        try:
            return self.firewall_client.get(project=PROJECT_ID, firewall=FIREWALL_RULE_NAME)
        except NotFound:
            return None

    def _add_ip_to_rule(self, ip_address):
        existing_rule = self._get_existing_rule()
        new_range = f"{ip_address}/32"

        if existing_rule:
            if new_range in existing_rule.source_ranges:
                return 

            updated_ranges = list(existing_rule.source_ranges)
            updated_ranges.append(new_range)
            
            op = self.firewall_client.patch(
                project=PROJECT_ID,
                firewall=FIREWALL_RULE_NAME,
                firewall_resource=compute_v1.Firewall(source_ranges=updated_ranges)
            )
        else:
            firewall_resource = {
                "name": FIREWALL_RULE_NAME,
                "direction": "INGRESS",
                "priority": 1000,
                "network": "global/networks/default",
                "allowed": [{"I_p_protocol": "tcp", "ports": [str(PROXY_PORT)]}],
                "source_ranges": [new_range],
                "target_tags": ["http-proxy-server"]
            }
            op = self.firewall_client.insert(project=PROJECT_ID, firewall_resource=firewall_resource)
        op.result()

    def _remove_ip_from_rule(self, ip_address):
        existing_rule = self._get_existing_rule()
        if not existing_rule:
            return

        target_range = f"{ip_address}/32"
        if target_range not in existing_rule.source_ranges:
            return

        updated_ranges = [ip for ip in existing_rule.source_ranges if ip != target_range]
        
        op = self.firewall_client.patch(
            project=PROJECT_ID,
            firewall=FIREWALL_RULE_NAME,
            firewall_resource=compute_v1.Firewall(source_ranges=updated_ranges)
        )
        op.result()

if __name__ == "__main__":
    # Standalone usage
    logging.basicConfig(level=logging.INFO)
    manager = FirewallManager()
    
    import sys
    import time
    if len(sys.argv) > 1 and sys.argv[1] == "revoke":
        # Force manual revoke without setting up atexit
        manager._authorized = True # Hack to allow revoke to run
        manager.revoke_current_ip()
    else:
        manager.authorize_current_ip()
        print("Running... Press Ctrl+C to test cleanup.")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            pass