# -*- coding: utf-8 -*-
"""ClaudeMPC control surface for Ableton Live 10 (embedded Python 2.7).

Threadless: no background threads (Live 10 starves them of the GIL). All socket
I/O and Live Object Model calls happen in update_display() on the main thread.
"""
from __future__ import absolute_import

from _Framework.ControlSurface import ControlSurface

from .commands import Commands
from .transport import Transport

PORT = 9879


class ClaudeMPC(ControlSurface):
    def __init__(self, c_instance):
        ControlSurface.__init__(self, c_instance)
        with self.component_guard():
            self._commands = Commands(self)
            self._transport = Transport(self._commands, port=PORT, log=self._log)
            self._transport.start()
        self.show_message("ClaudeMPC listening on port %d" % PORT)

    def _log(self, msg):
        self.log_message("ClaudeMPC: " + msg)

    def update_display(self):
        ControlSurface.update_display(self)
        try:
            self._transport.poll()
        except Exception as e:
            self._log("poll error: %r" % (e,))
        self._commands.tick()

    def disconnect(self):
        try:
            self._transport.close()
        finally:
            ControlSurface.disconnect(self)
