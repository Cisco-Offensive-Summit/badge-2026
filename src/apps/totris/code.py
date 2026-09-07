import supervisor
supervisor.runtime.autoreload = False
import time
import badge.screens
from apps.totris.totris import Totris

try:
    Totris().run()
except Exception as e:
    badge.screens.epd_print_exception(e)
    time.sleep(60)

supervisor.reload()