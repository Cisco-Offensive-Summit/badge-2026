from microcontroller import reset
import supervisor
import time
import badge.screens
from badge.screens import epd_print_exception
from apps.sequencer.sequencer import SequencerApp

supervisor.runtime.autoreload = False

try:
    tones = SequencerApp(badge.screens.LCD, badge.screens.EPD)
    tones.run()
except Exception as e:
    # Put the traceback on the EPD so failures are visible without a serial
    # console, matching the other apps.
    epd_print_exception(e)
    time.sleep(60)

reset()
