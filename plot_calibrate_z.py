#!/usr/bin/env python2
from __future__ import print_function
import optparse
import os
import ntpath
import sys
from textwrap import wrap
import numpy as np
import matplotlib
sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                             '..', 'klippy', 'extras'))

MAX_TITLE_LENGTH = 75


def parse_log(logname):
    with open(logname) as f:
        return np.loadtxt(logname, skiprows=1, comments='#', delimiter=',')


def cal_offset(singleSet):
    toAppend = np.array([])
    for i in range(len(singleSet)):
        row = singleSet[i]
        toAppend = np.append(toAppend, [row[2]-(row[1]-row[0])])

    return np.insert(singleSet, 3, toAppend, axis=1)


def plot_data(lognames, data, name, color='blue'):

    fontP = matplotlib.font_manager.FontProperties()
    fontP.set_size('x-small')
    data_len = len(data)
    fig, ax = matplotlib.pyplot.subplots()
    ax.set_xlabel('Sample# (Total:%d)' % (data_len))
    ax.set_ylabel('Z-Position')

    dStd = np.std(data)
    dMax = np.max(data)
    dMin = np.min(data)
    dMedian = np.median(data)
    dAvg = np.average(data)

    txt = '%s min:%.3f max: %.3f range: %.3f avg: %.3f median: %.3f std: %.3f' % (
        name, dMin, dMax, dMax-dMin, dAvg, dMedian, dStd)
    print(txt)
    ax.plot(range(data_len), data, label=txt, color=color)

    title = "%s, Z-Probe accuracy measurements (%s)" % (
        name, ', '.join(lognames))
    ax.set_title("\n".join(wrap(title, MAX_TITLE_LENGTH)))
    ax.xaxis.set_minor_locator(matplotlib.ticker.MultipleLocator(5))
    ax.yaxis.set_minor_locator(matplotlib.ticker.AutoMinorLocator())
    ax.ticklabel_format(axis='y', style='scientific', scilimits=(0, 0))
    ax.grid(which='major', color='grey')
    ax.grid(which='minor', color='lightgrey')

    ax.legend(loc='upper right', prop=fontP)

    fig.tight_layout()
    return fig

######################################################################
# Startup
######################################################################


def setup_matplotlib(output_to_file):
    global matplotlib
    if output_to_file:
        matplotlib.rcParams.update({'figure.autolayout': True})
        matplotlib.use('Agg')
    import matplotlib.pyplot
    import matplotlib.dates
    import matplotlib.font_manager
    import matplotlib.ticker


def main():
    # Parse command-line arguments
    usage = "%prog [options] <logs>"
    opts = optparse.OptionParser(usage)
    opts.add_option("-o", "--output", type="string", dest="output",
                    default=None, help="filename of output graph")

    options, args = opts.parse_args()
    if len(args) < 1:
        opts.error("Incorrect number of arguments")

    # Parse data
    # here we handle parsing of multiple input files! returns [dataOfFileOne, dataOfFileTwo...]
    parsedData = [parse_log(fn) for fn in args]
    # single is of from sing: [[nozzle, switch, bed],...] transforms to -> [[nozzle, switch, bed, offset]]
    parsedData = [cal_offset(single) for single in parsedData]

    setup_matplotlib(options.output is not None)

    fig1 = plot_data(args, [i[0] for i in parsedData[0]], 'Nozzle')
    fig2 = plot_data(args, [i[1]
                     for i in parsedData[0]], 'Switch', color='purple')
    fig3 = plot_data(args, [i[2] for i in parsedData[0]], 'Bed', color='green')
    fig4 = plot_data(args, [i[3]
                     for i in parsedData[0]], 'Offset', color='red')

    # Show graph
    if options.output is None:
        matplotlib.pyplot.show()
    else:
        head, tail = os.path.split(options.output)
        filename = os.path.splitext(tail)

        fig1.set_size_inches(8, 6)
        fig1.savefig(os.path.join(head, filename[0] + '_nozzle'+filename[1]))
        fig2.set_size_inches(8, 6)
        fig2.savefig(os.path.join(head, filename[0] + '_switch'+filename[1]))
        fig3.set_size_inches(8, 6)
        fig3.savefig(os.path.join(head, filename[0] + '_bed'+filename[1]))
        fig4.set_size_inches(8, 6)
        fig4.savefig(os.path.join(head, filename[0] + '_offset'+filename[1]))


if __name__ == '__main__':
    main()
