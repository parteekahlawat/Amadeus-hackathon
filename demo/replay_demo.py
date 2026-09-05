#!/usr/bin/env python3
"""Replay the KubeQA demo output with realistic typing animation for live presentation."""

import time
import sys
import os

FAST = "--fast" in sys.argv

def type_line(line, delay=None):
    if delay is None:
        if "━━━" in line or "══" in line or "───" in line:
            delay = 0.005 if FAST else 0.015
        elif "PHASE" in line:
            delay = 0.01 if FAST else 0.04
        elif line.strip().startswith("🔴") or line.strip().startswith("✗"):
            delay = 0.008 if FAST else 0.03
        elif line.strip().startswith("✓") or line.strip().startswith("🟢"):
            delay = 0.008 if FAST else 0.025
        elif line.strip().startswith("🟠") or line.strip().startswith("🟡"):
            delay = 0.006 if FAST else 0.02
        elif line.strip().startswith("→") or line.strip().startswith("↻"):
            delay = 0.005 if FAST else 0.015
        else:
            delay = 0.003 if FAST else 0.012

    for char in line:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\n")
    sys.stdout.flush()


def pause(seconds):
    if FAST:
        time.sleep(seconds * 0.2)
    else:
        time.sleep(seconds)


def main():
    demo_file = os.path.join(os.path.dirname(__file__), "demo_output.txt")

    with open(demo_file) as f:
        lines = f.readlines()

    os.system("clear")

    for line in lines:
        line = line.rstrip("\n")

        if "PHASE" in line and "───" in line:
            pause(1.2)
            type_line(line)
            pause(0.5)
        elif "━━━" in line or "══" in line or "───" in line:
            type_line(line)
            pause(0.3)
        elif "PIPELINE COMPLETE" in line:
            pause(1.5)
            type_line(line)
        elif line.strip().startswith("🔴"):
            pause(0.25)
            type_line(line)
        elif line.strip().startswith("✓ HEALED"):
            pause(0.8)
            type_line(line, 0.02 if FAST else 0.05)
        elif line.strip().startswith("✗"):
            pause(0.5)
            type_line(line, 0.015 if FAST else 0.04)
        elif "Quality Score:" in line or "Verdict:" in line or "Recommendation:" in line:
            pause(0.5)
            type_line(line, 0.015 if FAST else 0.04)
        elif line.strip().startswith("Self-healing"):
            pause(0.8)
            type_line(line, 0.01 if FAST else 0.035)
        elif "done" in line and "[" in line and "/" in line:
            pause(0.6)
            type_line(line)
        elif line.strip().startswith("test_"):
            pause(0.15)
            type_line(line)
        elif line.strip() == "":
            print()
            pause(0.08)
        else:
            type_line(line)

    pause(1.0)


if __name__ == "__main__":
    print("\033[36mKubeQA Shield — Live Demo\033[0m")
    print("Press Enter to start..." if not FAST else "Running in fast mode...")
    if not FAST:
        input()
    main()
