#!/usr/bin/env python
#
# lockstat      Monitor contention and wait times on locks and threads.
#
# USAGE: lockstat ... TODO
#
# Licensed under the Apache License, Version 2.0 (the "License")
# Copyright (C) 2016 Sasha Goldshtein.

from bcc import BPF
from time import sleep
import argparse

# TODO Emulate lockstat(1M) semantics from Sun
#      http://docs.oracle.com/cd/E19253-01/816-5166/lockstat-1m/index.html
#
# Grab wait events (contention) and hold events. Collect the time spent waiting
# for each lock by each thread, and the time spent inside each lock by each
# thread. Lock types can include mutex, RWL, spinlock, and so on. What's
# common across them is that there is an `enter` and `exit` function. The hold
# time is the delta between `enter` return and exit, the wait time is the delta
# between `enter` entry and its return.
#
# In default mode, just grab the caller's IP for each event, not the full
# stack trace. In detailed mode, grab the full stack trace.
# In default mode, just grab the number of times an event occurred. In detailed
# mode, grab the timing information and record a histogram of wait and hold
# times per lock.
#
# TODO Should this be per-thread? Sun's lockstat doesn't take threads into
# account when reporting wait and hold times, only the stack/method.
#
# TODO One more thing that Sun's lockstat doesn't do it wait graph tracing,
# so it can tell you that a thread is deadlocked. Need to think if it belongs
# in this tool or some dedicated `waitchain` tool.

class BaseTracer(object):
    pass

class PMutexTracer(BaseTracer):
    pass

class SpinlockTracer(BaseTracer):
    pass

class Tool(object):
    _examples = "TODO" # TODO

    def __init__(self):
        parser = argparse.ArgumentParser(description=
                "Monitor contention and wait times on locks and threads.",
                formatter_class=argparse.RawDescriptionHelpFormatter,
                epilog=Tool._examples)
        parser.add_argument("-p", "--pid", type=int,
                help="id of the process to trace (optional)")
        parser.add_argument("-v", "--verbose", action="store_true",
                help="print resulting BPF program code before executing")
        parser.add_argument("-i", "--interval", type=int,
                help="interval between printouts")
        parser.add_argument("-c", "--count", type=int,
                help="number of printouts before quitting")
        self.args = parser.parse_args()

    def _generate_program(self):
        pass

    def _attach(self):
        pass

    def _main_loop(self):
        pass

    def run(self):
        pass

if __name__ == "__main__":
    Tool().run()
