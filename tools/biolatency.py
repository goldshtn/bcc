#!/usr/bin/python
# @lint-avoid-python-3-compatibility-imports
#
# biolatency    Summarize block device I/O latency as a histogram.
#               For Linux, uses BCC, eBPF.
#
# USAGE: biolatency [-h] [-T] [-Q] [-m] [-D] [interval] [count]
#
# Copyright (c) 2015 Brendan Gregg.
# Licensed under the Apache License, Version 2.0 (the "License")
#
# 20-Sep-2015   Brendan Gregg     Created this.
# 03-Apr-2017   Sasha Goldshtein  Migrated to use kernel tracepoints.

from __future__ import print_function
from bcc import BPF
from time import sleep, strftime
import argparse

# arguments
examples = """examples:
    ./biolatency            # summarize block I/O latency as a histogram
    ./biolatency 1 10       # print 1 second summaries, 10 times
    ./biolatency -mT 1      # 1s summaries, milliseconds, and timestamps
    ./biolatency -Q         # include OS queued time in I/O time
    ./biolatency -D         # show each disk device separately
"""
parser = argparse.ArgumentParser(
    description="Summarize block device I/O latency as a histogram.",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=examples)
parser.add_argument("-T", "--timestamp", action="store_true",
    help="include timestamp on output")
parser.add_argument("-Q", "--queued", action="store_true",
    help="include OS queued time in I/O time")
parser.add_argument("-m", "--milliseconds", action="store_true",
    help="millisecond histogram")
parser.add_argument("-D", "--disks", action="store_true",
    help="print a histogram per disk device")
parser.add_argument("interval", nargs="?", default=99999999,
    help="output interval, in seconds")
parser.add_argument("count", nargs="?", default=99999999,
    help="number of outputs")
args = parser.parse_args()
countdown = int(args.count)
debug = 0

# define BPF program
bpf_text = """
#include <uapi/linux/ptrace.h>
#include <linux/blkdev.h>

typedef struct disk_key {
    dev_t dev;
    u64 slot;
} disk_key_t;

typedef struct start_key {
    dev_t dev;
    sector_t sector;
} start_key_t;

BPF_HASH(start, start_key_t, u64);
STORAGE

TRACEPOINT_PROBE(block, START_PROBE)
{
    start_key_t key = {};
    key.dev = args->dev;
    key.sector = args->sector;
    u64 ts = bpf_ktime_get_ns();
    start.update(&key, &ts);
    return 0;
}

TRACEPOINT_PROBE(block, block_rq_complete)
{
    start_key_t key = {};
    key.dev = args->dev;
    key.sector = args->sector;
    u64 *tsp, delta;

    // fetch timestamp and calculate delta
    tsp = start.lookup(&key);
    if (tsp == 0) {
        return 0;   // missed issue
    }
    delta = bpf_ktime_get_ns() - *tsp;
    FACTOR

    // store as histogram
    STORE

    start.delete(&key);
    return 0;
}
"""

# code substitutions
if args.milliseconds:
    bpf_text = bpf_text.replace('FACTOR', 'delta /= 1000000;')
    label = "msecs"
else:
    bpf_text = bpf_text.replace('FACTOR', 'delta /= 1000;')
    label = "usecs"
if args.disks:
    bpf_text = bpf_text.replace('STORAGE',
        'BPF_HISTOGRAM(dist, disk_key_t);')
    bpf_text = bpf_text.replace('STORE',
        'disk_key_t hist = {}; hist.dev = args->dev; ' +
        'hist.slot = bpf_log2l(delta); dist.increment(hist);')
else:
    bpf_text = bpf_text.replace('STORAGE', 'BPF_HISTOGRAM(dist);')
    bpf_text = bpf_text.replace('STORE', 'dist.increment(bpf_log2l(delta));')
if args.queued:
    bpf_text = bpf_text.replace('START_PROBE', 'block_rq_insert')
else:
    bpf_text = bpf_text.replace('START_PROBE', 'block_rq_issue')

if debug:
    print(bpf_text)

# load BPF program
b = BPF(text=bpf_text)

diskname_cache = {}

def dev_to_disk(dev):
    major, minor = dev >> 20, dev & ((1 << 20) - 1)    # like in kdev_t.h
    if (major, minor) in diskname_cache:
        return diskname_cache[(major, minor)]

    for line in open("/proc/partitions").readlines():
        if "major" in line: continue
        parts = line.strip().split()
        if len(parts) != 4: continue
        mj, mn, name = int(parts[0]), int(parts[1]), parts[3]
        diskname_cache[(mj, mn)] = name

    return diskname_cache.get((major, minor), "[unknown]")

print("Tracing block device I/O... Hit Ctrl-C to end.")

# output
exiting = 0 if args.interval else 1
dist = b.get_table("dist")
while (1):
    try:
        sleep(int(args.interval))
    except KeyboardInterrupt:
        exiting = 1

    print()
    if args.timestamp:
        print("%-8s\n" % strftime("%H:%M:%S"), end="")

    dist.print_log2_hist(label, "disk", section_print_fn=dev_to_disk)
    dist.clear()

    countdown -= 1
    if exiting or countdown == 0:
        exit()
