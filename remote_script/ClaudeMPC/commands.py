# -*- coding: utf-8 -*-
"""Command handlers. Run on Live's main thread from update_display()."""
from __future__ import absolute_import

import Live

SCRIPT_VERSION = "0.1.0"


class Commands(object):
    def __init__(self, surface):
        self.surface = surface
        self._effects_cache = None
        self.table = {
            "ping": self.ping,
            "spike_load_effect": self.spike_load_effect,
        }

    @property
    def song(self):
        return self.surface.song()

    @property
    def app(self):
        return Live.Application.get_application()

    def __call__(self, cmd, params):
        fn = self.table.get(cmd)
        if fn is None:
            raise KeyError(u"unknown command: %s" % cmd)
        return fn(**params)

    # -- commands ----------------------------------------------------------
    def ping(self):
        app = self.app
        return {
            "live_version": "%d.%d.%d" % (app.get_major_version(), app.get_minor_version(),
                                          app.get_bugfix_version()),
            "tempo": self.song.tempo,
            "script_version": SCRIPT_VERSION,
        }

    def spike_load_effect(self, target="master", index=0, name="Utility"):
        """DEV ONLY (Phase 1 spike): load a stock audio effect onto master/return/track."""
        song = self.song
        if target == "master":
            track = song.master_track
        elif target == "return":
            track = song.return_tracks[int(index)]
        elif target == "track":
            track = song.tracks[int(index)]
        else:
            raise ValueError(u"target must be master|return|track")

        item = self._find_effect(name)
        if item is None:
            raise LookupError(u"stock effect not found in browser: %s" % name)

        report = {"target": target, "index": index, "effect": unicode(item.name)}
        before = len(track.devices)
        prev_selected = song.view.selected_track
        browser = self.app.browser
        insert_mode_set = False
        try:
            song.view.selected_track = track
            browser.hotswap_target = None
            try:
                track.view.device_insert_mode = Live.Track.DeviceInsertMode.selected_right
                insert_mode_set = True
            except Exception as e:
                report["insert_mode_error"] = unicode(e)
            browser.load_item(item)
        finally:
            if insert_mode_set:
                try:
                    track.view.device_insert_mode = Live.Track.DeviceInsertMode.default
                except Exception:
                    pass
            song.view.selected_track = prev_selected

        report["devices_before"] = before
        report["devices_after"] = len(track.devices)
        report["device_names"] = [unicode(d.name) for d in track.devices]
        report["selection_restored"] = song.view.selected_track == prev_selected
        report["loaded"] = report["devices_after"] > before
        return report

    # -- helpers -----------------------------------------------------------
    def _find_effect(self, name):
        if self._effects_cache is None:
            cache = {}
            for child in self.app.browser.audio_effects.children:
                cache[unicode(child.name).lower()] = child
            self._effects_cache = cache
        item = self._effects_cache.get(unicode(name).lower())
        if item is not None and item.is_loadable:
            return item
        return None
