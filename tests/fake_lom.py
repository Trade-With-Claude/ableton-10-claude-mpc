"""Duck-typed fakes of the Live 10 Object Model, enough for lom.py and ops.py."""

import math


class Param:
    def __init__(self, name, value, lo=0.0, hi=1.0, quantized=False, items=(), fmt=None):
        self.name = name
        self._value = value
        self.min = lo
        self.max = hi
        self.is_quantized = quantized
        self.value_items = list(items)
        self.is_enabled = True
        self.automation_state = 0  # 0 none, 1 playing, 2 overridden
        self._fmt = fmt or (lambda v: "%.2f" % v)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        if not self.min <= v <= self.max:  # Live raises on out-of-range writes
            raise ValueError("value %r out of range [%r, %r]" % (v, self.min, self.max))
        self._value = v

    def str_for_value(self, v):
        if self.is_quantized and self.value_items:
            return self.value_items[int(v)]
        return self._fmt(v)

    def __str__(self):
        return self.str_for_value(self.value)


def db(v):
    return "%.1f dB" % v


# Live's mixer params are normalized 0-1 with a non-linear dB display:
# volume 0.85 = 0 dB, 1.0 = +6 dB; sends 1.0 = 0 dB; pan -1..1 shown as 50L..C..50R.
def vol_fmt(v):
    if v <= 0:
        return "-inf dB"
    if v >= 0.85:
        return "%.1f dB" % (6.0 * (v - 0.85) / 0.15)
    return "%.1f dB" % (40.0 * math.log10(v / 0.85))


def vol_value(dbv):
    return 0.85 + dbv * 0.15 / 6.0 if dbv >= 0 else 0.85 * 10 ** (dbv / 40.0)


def send_fmt(v):
    return "-inf dB" if v <= 0 else "%.1f dB" % (40.0 * math.log10(v))


def send_value(dbv):
    return 0.0 if dbv <= -70 else 10 ** (dbv / 40.0)


def pan_fmt(v):
    n = int(round(abs(v) * 50))
    return "C" if n == 0 else "%d%s" % (n, "L" if v < 0 else "R")


def on_param(on=True):
    return Param("Device On", 1.0 if on else 0.0, quantized=True, items=["Off", "On"])


class Device:
    def __init__(self, name, class_name, params=(), type=2, chains=None, on=True):
        self.name = name
        self.class_name = class_name
        self.type = type
        self.parameters = [on_param(on)] + list(params)
        self.can_have_chains = chains is not None
        self.chains = chains or []


class DeviceList:
    """`devices` + `delete_device(i)`, shared by Track and Chain."""

    def delete_device(self, i):
        del self.devices[i]


class ChainMixer:
    def __init__(self, vol_db=0.0, pan=0.0):
        self.volume = Param("Chain Volume", vol_value(vol_db), 0.0, 1.0, fmt=vol_fmt)
        self.panning = Param("Chain Pan", pan, -1.0, 1.0, fmt=pan_fmt)


class Chain(DeviceList):
    def __init__(self, name, devices=(), mute=False, solo=False, vol_db=0.0):
        self.name = name
        self.devices = list(devices)
        self.mute = mute
        self.solo = solo
        self.mixer_device = ChainMixer(vol_db)


class Mixer:
    def __init__(self, vol_db=0.0, pan=0.0, sends=()):
        self.volume = Param("Track Volume", vol_value(vol_db), 0.0, 1.0, fmt=vol_fmt)
        self.panning = Param("Track Panning", pan, -1.0, 1.0, fmt=pan_fmt)
        self.sends = [Param("Send", send_value(v), 0.0, 1.0, fmt=send_fmt) for v in sends]


class Routing:
    def __init__(self, name):
        self.display_name = name


class Track(DeviceList):
    def __init__(self, name, devices=(), sends=(), midi=False, foldable=False, group=None,
                 output="Master", meters=(0.5, 0.4), audio_out=True, armable=True):
        self.name = name
        self.color = 0x00FF8800
        self.devices = list(devices)
        self.mixer_device = Mixer(sends=sends)
        self.mute = False
        self.solo = False
        self.has_midi_input = midi
        self.is_foldable = foldable
        self.fold_state = 0
        self.group_track = group
        self.can_be_armed = armable and not foldable
        self.arm = False
        self.output_routing_type = Routing(output)
        self.has_audio_output = audio_out
        self.output_meter_left, self.output_meter_right = meters
        self.clip_slots = [ClipSlot() for _ in range(8)]


class Clip:
    def __init__(self, length):
        self.length = length
        self.name = ""
        self.notes = ()

    def set_notes(self, notes):
        self.notes = tuple(self.notes) + tuple(notes)

    def get_notes(self, start, pitch, length, pitch_span):
        return self.notes


class ClipSlot:
    def __init__(self):
        self.clip = None

    @property
    def has_clip(self):
        return self.clip is not None

    def create_clip(self, length):
        if self.clip is not None:
            raise RuntimeError("slot already has a clip")
        self.clip = Clip(length)


class SongView:
    def __init__(self, song):
        self.selected_track = song.tracks[0] if song.tracks else None


class Song:
    def __init__(self, tracks, returns, master, tempo=174.0):
        self.tracks = tracks
        self.return_tracks = returns
        self.master_track = master
        self.tempo = tempo
        self.undo_begins = 0
        self.undo_ends = 0
        # transport, for the automation recorder
        self.is_playing = False
        self.current_song_time = 0.0
        self.record_mode = False
        self.session_automation_record = False
        self.loop = True
        self.signature_numerator = 4
        self.signature_denominator = 4
        self.back_to_arranger = False

        # Live 10 starts playback from the Arrangement insert marker; setting
        # current_song_time while stopped doesn't move it (seen in the Phase 7 UAT)
        self.insert_marker = None
        self.view = SongView(self)

    def create_midi_track(self, index):
        t = Track("%d-MIDI" % (len(self.tracks) + 1), midi=True)
        self.tracks.insert(len(self.tracks) if index == -1 else index, t)
        self.view.selected_track = t  # Live selects the new track

    def delete_track(self, index):
        del self.tracks[index]

    def start_playing(self):
        if self.insert_marker is not None:
            self.current_song_time = self.insert_marker
        self.is_playing = True

    def stop_playing(self):
        self.is_playing = False

    def begin_undo_step(self):
        self.undo_begins += 1

    def end_undo_step(self):
        self.undo_ends += 1


class FakeLoader:
    STOCK = {"eq eight": "Eq8", "utility": "StereoGain", "glue compressor": "GlueCompressor"}
    INSTRUMENTS = {"analog": "UltraAnalog", "operator": "Operator", "wavetable": "InstrumentVector"}

    def __init__(self, fail=False):
        self.fail = fail
        self.loads = []

    def check(self, name):
        if name.lower() not in self.STOCK:
            raise LookupError("stock effect not found in browser: %s" % name)

    def load(self, track, name, position, chain=None):
        if self.fail:
            raise RuntimeError("browser exploded")
        holder = chain if chain is not None else track
        dev = Device(name, self.STOCK[name.lower()])
        pos = len(holder.devices) if position is None else position
        holder.devices.insert(pos, dev)
        self.loads.append((holder.name, name, pos))
        return dev

    def check_instrument(self, name):
        if name.lower() not in self.INSTRUMENTS:
            raise LookupError("stock instrument not found in browser: %s" % name)

    def load_instrument(self, track, name):
        if self.fail:
            raise RuntimeError("browser exploded")
        if name.lower() == "wavetable":
            dev = FakeWavetable()
        else:
            dev = Device(name, self.INSTRUMENTS[name.lower()], type=1)
        track.devices.append(dev)
        self.loads.append((track.name, name, 0))
        return dev


def khs_output_gain(value=0.48714131116867065):
    """A kHs-Limiter-like plugin param: raw 0..1 -> -20..+20 dB, shown with a U+2212 minus."""
    def fmt(v):
        d = -20.0 + 40.0 * v
        return ("\u2212%.2f dB" % -d) if d < 0 else ("+%.2f dB" % d)
    return Param("Output gain", value, 0.0, 1.0, fmt=fmt)


def hz_fmt(v):
    """Auto Filter Frequency: raw 20..135 is a note number, shown in Hz/kHz."""
    f = 440.0 * 2 ** ((v - 69.0) / 12.0)
    return "%.0f Hz" % f if f < 1000 else "%.2f kHz" % (f / 1000.0)


def auto_filter():
    return Device("Auto Filter", "AutoFilter",
                  [Param("Frequency", 127.0, 20.0, 135.0, fmt=hz_fmt),
                   Param("Resonance", 0.2, 0.0, 1.25, fmt=lambda v: "%.2f" % v),
                   Param("LFO Amount", 0.0, 0.0, 30.0, fmt=lambda v: "%.1f" % v)])


def dnb_song():
    """Group 'DRUMS' (Kick, Snare) + 'Bässe ✦ Sub', 2 returns, master with Glue + plugin."""
    drums = Track("DRUMS", foldable=True, sends=(-70.0, -70.0),
                  devices=[Device("Glue Compressor", "GlueCompressor",
                                  [Param("Threshold", -12.0, -40.0, 0.0, fmt=db),
                                   Param("Ratio", 1, quantized=True, items=["2", "4", "10"]),
                                   Param("S/C EQ Type", 0, 0, 5, quantized=True,
                                         items=["Low Shelf", "Bell", "High Shelf", "Low pass", "Peak", "High pass"]),
                                   Param("S/C EQ Freq", 0.3, fmt=lambda v: "%.0f Hz" % (20 * 1000 ** v)
                                         if 20 * 1000 ** v < 1000 else "%.2f kHz" % (0.02 * 1000 ** v)),
                                   Param("Makeup", 0.0, 0.0, 20.0, fmt=db)])])
    kick = Track("Kick", group=drums, sends=(-70.0, -70.0), output="DRUMS")
    snare = Track("Snare", group=drums, sends=(-12.0, -70.0), output="DRUMS")
    rack = Device("Bass Rack", "AudioEffectGroupDevice", chains=[
        Chain("Sub", [Device("EQ Eight", "Eq8", [Param("1 Frequency A", 0.3)])], vol_db=-3.0),
        Chain("Mid", [Device("Saturator", "Saturator", [Param("Drive", 6.0, 0.0, 36.0, fmt=db)]),
                      Device("Inner", "AudioEffectGroupDevice",
                             chains=[Chain("Deep", [Device("Utility", "StereoGain")])])]),
    ])
    bass = Track("Bässe ✦ Sub", midi=True, sends=(-70.0, -70.0),
                 devices=[Device("Serum", "AuPluginDevice", [Param("Macro 1", 0.25)], type=1), rack])
    ret_a = Track("A-Reverb", sends=(-70.0, -70.0), armable=False,
                  devices=[Device("Reverb", "Reverb")])
    ret_b = Track("B-Delay", sends=(-70.0, -70.0), armable=False)
    master = Track("Master", armable=False, meters=(0.9, 0.95),
                   devices=[Device("Limiter", "Limiter", [Param("Ceiling", -0.3, -24.0, 0.0, fmt=db)]),
                            Device("kHs Limiter", "PluginDevice", [khs_output_gain()])])
    midi_fx = Track("MIDI only", midi=True, audio_out=False)
    return Song([drums, kick, snare, bass, midi_fx], [ret_a, ret_b], master)


class FakeWavetable(Device):
    """Live 10.1 WavetableDevice: wavetables, voices and the modulation matrix outside `parameters`."""
    TABLES = {"Basics": ["Basic Shapes", "Sine Saw", "Pulse Width"],
              "Synth": ["Analog Saw", "Bright Lead", "Hollow"]}

    def __init__(self):
        super().__init__("Wavetable", "InstrumentVector",
                         [Param("Osc 1 Transp", 0.0, -24.0, 24.0), Param("Osc 1 Pos", 0.0),
                          Param("Filter 1 Freq", 1.0), Param("Volume", 0.6)], type=1)
        self.oscillator_wavetable_categories = list(self.TABLES)
        self.oscillator_1_wavetable_category = 0
        self.oscillator_1_wavetable_index = 0
        self.oscillator_2_wavetable_category = 0
        self.oscillator_2_wavetable_index = 0
        self.oscillator_1_effect_mode = 0
        self.oscillator_2_effect_mode = 0
        self.mono_poly = 1
        self.poly_voices = 6
        self.unison_mode = 0
        self.unison_voice_count = 0
        self.filter_routing = 0
        self.visible_modulation_target_names = ["Filter 1 Freq"]
        self.matrix = {}

    @property
    def oscillator_1_wavetables(self):
        return self.TABLES[self.oscillator_wavetable_categories[self.oscillator_1_wavetable_category]]

    @property
    def oscillator_2_wavetables(self):
        return self.TABLES[self.oscillator_wavetable_categories[self.oscillator_2_wavetable_category]]

    def get_modulation_value(self, target, source):
        return self.matrix.get((self.visible_modulation_target_names[target], source), 0.0)

    def set_modulation_value(self, target, source, value):
        self.matrix[(self.visible_modulation_target_names[target], source)] = value

    def is_parameter_modulatable(self, param):
        return param.name != "Volume"

    def add_parameter_to_modulation_matrix(self, param):
        self.visible_modulation_target_names.append(param.name)
