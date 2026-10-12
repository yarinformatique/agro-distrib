import os
import threading
import time
import urllib.request
from django.apps import AppConfig

_KEEP_ALIVE_STARTED = False


class DistributionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'distribution'

    def ready(self):
        global _KEEP_ALIVE_STARTED
        if _KEEP_ALIVE_STARTED:
            return

        # Render injecte automatiquement RENDER_EXTERNAL_URL sur les Web Services
        target_base_url = (
            os.environ.get('KEEP_ALIVE_URL') or
            os.environ.get('RENDER_EXTERNAL_URL') or
            ''
        ).strip().rstrip('/')

        if not target_base_url:
            return

        _KEEP_ALIVE_STARTED = True
        ping_url = f"{target_base_url}/healthz"
        interval_seconds = int(os.environ.get('KEEP_ALIVE_INTERVAL', '600'))  # 10 minutes par défaut

        def _self_ping_loop():
            # Attendre que le serveur Gunicorn ait terminé son démarrage
            time.sleep(30)
            while True:
                try:
                    req = urllib.request.Request(
                        ping_url,
                        headers={'User-Agent': 'AgroDistrib-KeepAlive/1.0'}
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        _ = resp.status
                except Exception:
                    pass
                time.sleep(interval_seconds)

        thread = threading.Thread(target=_self_ping_loop, name="agrodistrib-keepalive", daemon=True)
        thread.start()

