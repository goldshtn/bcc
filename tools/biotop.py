#!/usr/bin/python
# @lint-avoid-python-3-compatibility-imports
#
# biotop  block device (disk) I/O by process.
#         For Linux, uses BCC, eBPF.
#
# USAGE: biotop.py [-h] [-C] [-r MAXROWS] [interval] [count]
#
# This uses in-kernel eBPF maps to cache process details (PID and comm) by I/O
# request, as well as a starting timestamp for calculating I/O latency.
#
# Copyright 2016 Netflix, Inc.
# Licensed under the Apache License, Version 2.0 (the "License")
#
# 06-Feb-2016   Brendan Gregg     Created this.
# 03-Apr-2017   Sasha Goldshtein  Migrated to kernel tracepoints.

from __future__ import print_function
from bcc import BPF
from time import sleep, strftime
import argparse
import signal
from subprocess import call

# arguments
examples = """examples:
    ./biotop            # block device I/O top, 1 second refresh
    ./biotop -C         # don't clear the screen
    ./biotop 5          # 5 second summaries
    ./biotop 5 10       # 5 second summaries, 10 times only
"""
parser = argparse.ArgumentParser(
    description="Block device (disk) I/O by process",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=examples)
parser.add_argument("-C", "--noclear", action="store_true",
    help="don't clear the screen")
parser.add_argument("-r", "--maxrows", default=20,
    help="maximum rows to print, default 20")
parser.add_argument("interval", nargs="?", default=1,
    help="output interval, in seconds")
parser.add_argument("count", nargs="?", default=99999999,
    help="number of outputs")
args = parser.parse_args()
interval = int(args.interval)
countdown = int(args.count)
maxrows = int(args.maxrows)
clear = not int(args.noclear)

# linux stats
loadavg = "/proc/loadavg"
diskstats = "/proc/diskstats"

# signal handler
def signal_ignore(signal, frame):
    print()

# load BPF program
b = BPF(text="""
#include <uapi/linux/ptrace.h>
#include <linux/blkdev.h>

// the key for the output summary
struct info_t {
    u32 pid;
    u32 major;
    u32 minor;
    char rwbs[8];
    char comm[TASK_COMM_LEN];
};

// the value of the output summary
struct val_t {
    u64 bytes;
    u64 us;
    u32 io;
};

// the key for correlating issue and completion
struct start_key_t {
    dev_t dev;
    sector_t sector;
};

// the value for correlated issue with I/O details
struct start_val_t {
    u32 pid;
    u64 ts;
    u64 bytes;
    char comm[TASK_COMM_LEN];
};

BPF_HASH(start, struct start_key_t, struct start_val_t);
BPF_HASH(counts, struct info_t, struct val_t);

TRACEPOINT_PROBE(block, block_rq_issue)
{
    struct start_key_t key = {};
    key.dev = args->dev;
    key.sector = args->sector;

    struct start_val_t val = {};
    val.pid = bpf_get_current_pid_tgid() >> 32;   // process id (not thread)
    val.ts = bpf_ktime_get_ns();
    if (args->nr_sector != 0) {
        val.bytes = args->nr_sector << 9;
    } else {
        val.bytes = args->bytes;
    }
    bpf_get_current_comm(&val.comm, sizeof(val.comm));

    start.update(&key, &val);

    return 0;
}

TRACEPOINT_PROBE(block, block_rq_complete)
{
    struct start_key_t key = {};
    key.dev = args->dev;
    key.sector = args->sector;

    struct start_val_t *start_valp;

    // fetch timestamp and calculate delta
    start_valp = start.lookup(&key);
    if (start_valp == 0) {
        return 0;    // missed tracing issue
    }

    struct val_t *valp, zero = {};
    u64 delta_us = (bpf_ktime_get_ns() - start_valp->ts) / 1000;

    // setup info_t key
    struct info_t info = {};
    info.major = MAJOR(args->dev);
    info.minor = MINOR(args->dev);
    info.pid = start_valp->pid;
    bpf_probe_read(&info.comm, sizeof(info.comm), start_valp->comm);

    valp = counts.lookup_or_init(&info, &zero);

    // save stats
    valp->us += delta_us;
    valp->bytes += start_valp->bytes;
    valp->io++;

    start.delete(&key);

    return 0;
}
""")

diskname_cache = {}

def dev_to_disk(major, minor):
    if (major, minor) in diskname_cache:
        return diskname_cache[(major, minor)]

    for line in open("/proc/partitions").readlines():
        if "major" in line: continue
        parts = line.strip().split()
        if len(parts) != 4: continue
        mj, mn, name = int(parts[0]), int(parts[1]), parts[3]
        diskname_cache[(mj, mn)] = name

    return diskname_cache.get((major, minor), "[unknown]")

print('Tracing... Output every %d secs. Hit Ctrl-C to end' % interval)

# output
exiting = 0
while 1:
    try:
        sleep(interval)
    except KeyboardInterrupt:
        exiting = 1

    # header
    if clear:
        call("clear")
    else:
        print()
    with open(loadavg) as stats:
        print("%-8s loadavg: %s" % (strftime("%H:%M:%S"), stats.read()))
    print("%-6s %-16s %1s %-3s %-3s %-8s %5s %7s %6s" % ("PID", "COMM",
        "D", "MAJ", "MIN", "DISK", "I/O", "Kbytes", "AVGms"))

    # by-PID output
    counts = b.get_table("counts")
    line = 0
    for k, v in reversed(sorted(counts.items(),
                                key=lambda counts: counts[1].bytes)):

        diskname = dev_to_disk(k.major, k.minor)

        # print line
        avg_ms = (float(v.us) / 1000) / v.io
        print("%-6d %-16s %1s %-3d %-3d %-8s %5s %7s %6.2f" % (k.pid,
            k.comm.decode(), k.rwbs, k.major, k.minor,
            diskname, v.io, v.bytes / 1024, avg_ms))

        line += 1
        if line >= maxrows:
            break
    counts.clear()

    countdown -= 1
    if exiting or countdown == 0:
        print("Detaching...")
        exit()
