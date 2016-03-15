"""
Vessel statistics
"""

import gpsdio
import sys
import datetime
import rolling_measures
import numpy
from numpy import *
from numpy.lib.recfunctions import *

def add_measures(x, windowSize = 12*60*60, verbose=True, err=sys.stderr):
    x = x[x['course'] != Inf]
    x = x[x['speed'] != Inf]

    # Sort by mmsi, then by timestamp
    x = x[lexsort((x['timestamp'], x['mmsi']))]

    x = append_fields(x, 'measure_speed', [], dtypes='<f8', fill_value=0.0)
    x = append_fields(x, 'measure_course', [], dtypes='<f8', fill_value=0.0)
    x = append_fields(x, 'measure_speedstddev_%s' % windowSize, [], dtypes='<f8', fill_value=0.0)
    x = append_fields(x, 'measure_speedavg_%s' % windowSize, [], dtypes='<f8', fill_value=0.0)
    x = append_fields(x, 'measure_coursestddev_%s' % windowSize, [], dtypes='<f8', fill_value=0.0)
    x = append_fields(x, 'measure_new_score_%s' % windowSize, [], dtypes='<f8', fill_value=0.0)

    x = x.filled()

    # Normalize speed and heading
    speed = x['speed'] / 17.0
    x['measure_speed'] = 1 - where(speed > 1.0, 1.0, speed)
    x['measure_course'] = x['course'] / 360.0

    # Calculate rolling stddev/avg of course and speed
    start_idx = 0
    for end_idx in xrange(0, x.shape[0]):
        if verbose and end_idx % 1000 == 0:
            err.write("addmeasures: %s\n" % (end_idx,))
            err.flush()

        while (x['mmsi'][start_idx] != x['mmsi'][end_idx]
               or x['timestamp'][start_idx] < x['timestamp'][end_idx] - windowSize):
            start_idx += 1
        assert start_idx <= end_idx
        window = x[start_idx:end_idx + 1]   
        x['measure_speedstddev_%s' % windowSize][end_idx] = window['measure_speed'].std()
        x['measure_speedavg_%s' % windowSize][end_idx] = numpy.average(window['measure_speed'])
        x['measure_coursestddev_%s' % windowSize][end_idx] = window['measure_course'].std()

        if isnan(x['measure_coursestddev_%s' % windowSize][end_idx]):
            print "XXXXXX", start_idx, end_idx + 1

    return x

if __name__ == '__main__':
    numpy.savez_compressed(
        sys.argv[2],
        x=add_measures(
            numpy.load(sys.argv[1])['x'],
            windowSize = 12*60*60,
            verbose=True,
            err=sys.stderr))
