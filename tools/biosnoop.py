#!/usr/bin/python
# @lint-avoid-python-3-compatibility-imports
#
# biosnoop  Trace block device I/O and print details including issuing PID.
#           For Linux, uses BCC, eBPF.
#
# USAGE: biosnoop [-h] [-Q]
#
# Copyright (c) 2015 Brendan Gregg.
# Licensed under the Apache License, Version 2.0 (the "License")
#
# 16-Sep-2015   Brendan Gregg     Created this.
# 11-Feb-2016   Allan McAleavy    Updated for BPF_PERF_OUTPUT.
# 03-Apr-2017   Sasha Goldshtein  Migrated to use kernel tracepoints.

from __future__ import print_function
from bcc import BPF
import argparse
import ctypes as ct
import re

# arguments
examples = """examples:
    ./biosnoop          # trace block device I/O
    ./biosnoop -Q       # trace block device I/O including queue latency
"""
parser = argparse.ArgumentParser(description=
    "Trace block device I/O and print details including issuing PID.",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=examples)
parser.add_argument("-Q", "--queued", action="store_true", dest="queue",
    help="include OS queued time in I/O time")
args = parser.parse_args()

# load BPF program
program = """
#include <uapi/linux/ptrace.h>
#include <linux/blkdev.h>

struct key_t {
    dev_t dev;
    sector_t sector;
};

struct val_t {
    u64 tgid_pid;
    u64 start_ts;
#ifdef QUEUE_TIME
    u64 queue_ts;
#endif
    u32 bytes;
    char comm[TASK_COMM_LEN];
};

struct data_t {
    u64 tgid_pid;
    u64 delta;
    u64 sector;
    u64 len;
    u64 complete_ts;
    u32 major;
    u32 minor;
    char rwbs[8];
    char comm[TASK_COMM_LEN];
#ifdef QUEUE_TIME
    u64 queue_delta;
#endif
};

BPF_HASH(start, struct key_t, struct val_t);
BPF_PERF_OUTPUT(events);

#ifdef QUEUE_TIME
TRACEPOINT_PROBE(block, block_rq_insert)
{
    struct key_t key = {};
    key.dev = args->dev;
    key.sector = args->sector;

    struct val_t val = {};
    val.queue_ts = bpf_ktime_get_ns();
    val.tgid_pid = bpf_get_current_pid_tgid();
    bpf_get_current_comm(&val.comm, sizeof(val.comm));

    start.update(&key, &val);

    return 0;
}
#endif

TRACEPOINT_PROBE(block, block_rq_issue)
{
    struct key_t key = {};
    key.dev = args->dev;
    key.sector = args->sector;

    struct val_t val = {}, *valp;
#ifdef QUEUE_TIME
    valp = start.lookup(&key);
    if (valp == 0) {
        // missed enqueue
        return 0;
    }
    val = *valp;
#else
    bpf_get_current_comm(&val.comm, sizeof(val.comm));
    val.tgid_pid = bpf_get_current_pid_tgid();
#endif
    val.start_ts = bpf_ktime_get_ns();
    val.bytes = args->nr_sector << 9;
    if (val.bytes == 0) {
        val.bytes = args->bytes;
    }

    start.update(&key, &val);

    return 0;
}

TRACEPOINT_PROBE(block, block_rq_complete)
{
    struct key_t key = {};
    key.dev = args->dev;
    key.sector = args->sector;

    struct val_t *valp;
    struct data_t data = {};
    u64 ts;

    valp = start.lookup(&key);
    if (valp == 0) {
        // missed tracing issue
        return 0;
    }
    ts = bpf_ktime_get_ns();
    data.delta = ts - valp->start_ts;
#ifdef QUEUE_TIME
    data.queue_delta = valp->start_ts - valp->queue_ts;
#endif
    data.complete_ts = ts;
    data.tgid_pid = valp->tgid_pid;
    data.len = valp->bytes;
    data.sector = key.sector;
    data.major = MAJOR(key.dev);
    data.minor = MINOR(key.dev);
    bpf_probe_read(&data.rwbs, sizeof(data.rwbs), args->rwbs);
    bpf_probe_read(&data.comm, sizeof(data.comm), valp->comm);

    events.perf_submit(args, &data, sizeof(data));
    start.delete(&key);

    return 0;
}
"""
if args.queue:
    program = "#define QUEUE_TIME\n" + program
b = BPF(text=program)

TASK_COMM_LEN = 16  # linux/sched.h

class Data(ct.Structure):
    _fields_ = [
        ("tgid_pid", ct.c_ulonglong),
        ("delta", ct.c_ulonglong),
        ("sector", ct.c_longlong),
        ("len", ct.c_ulonglong),
        ("complete_ts", ct.c_ulonglong),
        ("major", ct.c_uint),
        ("minor", ct.c_uint),
        ("rwbs", ct.c_char * 8),
        ("comm", ct.c_char * TASK_COMM_LEN)
    ] + ([("queue_delta", ct.c_ulonglong)] if args.queue else [])

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

# header
if args.queue:
    print("%-14s %-14s %-6s %-7s %-4s %-9s %-7s %7s %7s" %
         ("TIME(s)", "COMM", "PID", "DISK", "T", "SECTOR",
          "BYTES", "LAT(ms)", "QLAT(ms)"))
else:
    print("%-14s %-14s %-6s %-7s %-4s %-9s %-7s %7s" %
         ("TIME(s)", "COMM", "PID", "DISK", "T", "SECTOR", "BYTES", "LAT(ms)"))

start_ts = 0
prev_ts = 0
delta = 0

# process event
def print_event(cpu, data, size):
    event = ct.cast(data, ct.POINTER(Data)).contents

    global start_ts
    global prev_ts
    global delta

    disk_name = dev_to_disk(event.major, event.minor)

    if start_ts == 0:
        prev_ts = start_ts

    if start_ts == 1:
        delta = float(delta) + (event.complete_ts - prev_ts)

    if args.queue:
        print("%-14.9f %-14.14s %-6s %-7s %-4s %-9d %-7d %7.3f %7.3f" % (
            delta / 1000000000, event.comm.decode(), event.tgid_pid >> 32,
            disk_name.decode(), event.rwbs.decode(), event.sector,
            event.len, float(event.delta) / 1000000000,
            float(event.queue_delta) / 1000000000))
    else:
        print("%-14.9f %-14.14s %-6s %-7s %-4s %-9d %-7d %7.3f" % (
            delta / 1000000000, event.comm.decode(), event.tgid_pid >> 32,
            disk_name.decode(), event.rwbs.decode(), event.sector,
            event.len, float(event.delta) / 1000000000))

    prev_ts = event.complete_ts
    start_ts = 1

# loop with callback to print_event
b["events"].open_perf_buffer(print_event, page_cnt=64)
while 1:
    b.kprobe_poll()
