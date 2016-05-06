"""
Vessel statistics
"""

import sys
import datetime
import itertools
import numpy
import rolling_measures


def AddNormalizedMeasures(messages):
    for row in messages:
        heading = row.get('heading')
        if heading is not None:
            row['measure_heading'] = heading / 360.0

        course = row.get('course')
        if course is not None:
            row['measure_course'] = course / 360.0
            row['measure_cos_course'] = numpy.cos(numpy.radians(course)) / numpy.sqrt(2)
            row['measure_sin_course'] = numpy.sin(numpy.radians(course)) / numpy.sqrt(2)

        speed = row.get('speed')
        if speed is not None:
            row['measure_speed'] = 1.0 - min(1.0, speed / 17.0)

        turn = row.get('turn')
        if turn is not None:
            try:
                row['measure_turn'] = min(1.0, abs(turn) / 126.0)
            except Exception:
                assert False, "{} {}".format(turn, type(turn))

        # Since `dict.get()` defaults to `None`, `tools.AbsentKey` makes sure we don't
        # add a `distance_from_port = 1` to messages that don't have a value, which
        # are mainly non-posits.

        if 'distance_from_port' in row:
            distance_from_port = row['distance_from_port']
            if distance_from_port is None:
                row['measure_distance_from_port'] = 1.0
            else:
                row['measure_distance_from_port'] = min(1.0, distance_from_port / 30.0) # XXX check units of distance from port (might be meters!)
        yield row


class AddWindowMeasures(object):

    """
    Adds window based measures to track points.  Input is sorted by mmsi,track,timestamp.
    Requires two handles to the _same_ stream of messages for the two ends of the window.
    """

    def __init__(self, messages, window_size=datetime.timedelta(seconds=60 * 60)):

        """
        Iterate to get messages with additional measures.

        Parameters
        ----------
        stream: iter
            GPSd messages.
        window_size : datetime.timedelta, optional
            Size of window in seconds.
        """

        stream1, stream2 = itertools.tee(messages, 2)
        self.startIn = self.load_lines(stream1)
        self.endIn = self.load_lines(stream2)
        self.current_track = None
        self.window_size = window_size
        self.startidx = -1
        self._iterator = None

    def __iter__(self):
        if not self._iterator:
            self._iterator = self.process()
        return self._iterator

    def __next__(self):
        return next(self._iterator)

    next = __next__

    def load_lines(self, in_file):
        for idx, line in enumerate(in_file):
            yield idx, line

    def add_measures_to_row(self):
        s = self.stats.get()
        # Knots...
        s['measure_pos'] = (s['measure_pos'] * 60) / (self.window_size.total_seconds() / 60 / 60)
        # Normalize to "normal" vessel speed
        s['measure_pos'] /= 17.0
        s['measure_pos'] = min(1.0, s['measure_pos'])

        s = {"%s_%s" % (key, int(self.window_size.total_seconds())): value
             for key, value in s.iteritems()}

        EPSILON = 1e-3
        for key, value in s.items():
            if 'stddev' in key:
                s[key + "_log"] = float(numpy.log10(value + EPSILON))
#                 if value == 0.0:
#                     s[key + "_log"] = float(numpy.finfo(numpy.dtype("f4")).min)
#                 else:
#                     s[key + "_log"] = float(numpy.log10(value))

        self.end.update(s)

    def start_track(self):
        self.current_track = self.end
        self.prev = None
        self.stats = rolling_measures.Stats({
            'measure_coursestddev' : rolling_measures.StatSum(
                rolling_measures.Stat("measure_cos_course", rolling_measures.StdDev),
                rolling_measures.Stat("measure_sin_course", rolling_measures.StdDev)),
            "measure_speedstddev": rolling_measures.Stat("measure_speed", rolling_measures.StdDev),
            "measure_courseavg": rolling_measures.Stat("measure_course", rolling_measures.Avg),
            "measure_speedavg": rolling_measures.Stat("measure_speed", rolling_measures.Avg),
            "measure_latavg": rolling_measures.Stat("lat", rolling_measures.Avg),
            "measure_lonavg": rolling_measures.Stat("lon", rolling_measures.Avg),
            "measure_pos": rolling_measures.StatSum(
                rolling_measures.Stat("lat", rolling_measures.StdDev),
                rolling_measures.Stat("lon", rolling_measures.StdDev))
        })

    def process(self):
        for self.endidx, self.end in self.endIn:

            if (not self.current_track or
                    self.end.get('mmsi', None) != self.current_track.get('mmsi', None) or
                    self.end.get('seg_id', None) != self.current_track.get('seg_id', None)):
                while self.startidx < self.endidx:
                    self.startidx, self.start = self.startIn.next()
                self.start_track()

            self.stats.add(self.end)

            if 'timestamp' in self.end:
                while (   not self.start
                       or 'timestamp' not in self.start
                       or self.end['timestamp'] - self.start['timestamp'] > self.window_size):
                    if self.start:
                        self.stats.remove(self.start)
                    self.startidx, self.start = self.startIn.next()

            self.add_measures_to_row()

            out = self.end.copy() # XXX do we need to copy here?

            yield out


class AddPairMeasures(object):

    """
    Adds pair based measures to track points.  Input is sorted by mmsi,track,timestamp.
    """

    diffkeys = [
        'lon', 'lat', 'timestamp', 'measure_heading', 'measure_turn',
        'measure_course', 'measure_speed']

    def __init__(self, messages, window_size=datetime.timedelta(seconds=60 * 60)):

        self.messages = messages
        self.current_track = None
        self._iterator = None
        self.prev = None

    def __iter__(self):
        if not self._iterator:
            self._iterator = self.process()
        return self._iterator

    def __next__(self):
        return next(self._iterator)

    next = __next__

    def process(self):
        for msg in self.messages:
            if not self.current_track or msg.get('mmsi', None) != self.current_track.get('mmsi', None) or msg.get('seg_id', None) != self.current_track.get('seg_id', None):
                self.prev = None
                self.current_track = msg

            if self.prev is None:
                self.prev = msg
            msg.update({key + "_diff": abs(msg[key] - self.prev[key])
                             for key in self.diffkeys
                             if key in msg and key in self.prev})
            self.prev = msg

            timestamp_diff = msg.get('timestamp_diff')
            if timestamp_diff is not None:
                msg['timestamp_diff'] = timestamp_diff.total_seconds()

            yield msg



def AddMeasures(messages, windows = [1800, 3600, 10800, 21600, 43200, 86400]):
    filtered = (msg for msg in messages if msg.get('course') is not None and
                                           msg.get('speed') is not None and
                                           msg.get('timestamp') is not None)

    filtered = AddNormalizedMeasures(filtered)

    for window_size in windows:
        filtered = AddWindowMeasures(filtered, datetime.timedelta(seconds=window_size))

    return filtered

def AddMeasuresComplex(messages, windows = [1800, 3600, 10800, 21600, 43200, 86400]):
    # If we need to keep all of the elements in the sequence, something
    # like this (untested) might work. Might be better to modify
    # rolling measures to ignore None values though.

    messages = AddNormalizedMeasures(messages)

    # I'm sure there's a better way to do this using itertools.tee or some such
    filtered = (msg for msg in messages if msg.get('course') is not None and
                                           msg.get('speed') is not None and
                                           msg.get('timestamp') is not None)

    antifiltered = (msg for msg in messages if not (msg.get('course') is not None and
                                           msg.get('speed') is not None and
                                           msg.get('timestamp') is not None))

    fields_ok = (msg.get('course') is not None and
                  msg.get('speed') is not None and
                  msg.get('timestamp') is not None for msg in messages)


    for window_size in windows:
        filtered = AddWindowMeasures(filtered, datetime.timedelta(seconds=window_size))

    for is_ok in fields_ok:
        if is_ok:
            yield filtered.next()
        else:
            yield antifiltered.next()
