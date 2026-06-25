"""Cycle N runs and log each run's melody trio (JSON lines)."""

import json
import sys
import time

from ravenswatch.controller import GameController
from ravenswatch.flow import restart_and_start, start_run
from ravenswatch.memory import MemoryReader

N = int(sys.argv[1]) if len(sys.argv) > 1 else 14


def read_trio(reader, retries=3):
    for _ in range(retries):
        info = reader.read_run_info()
        if info:
            return [m.display_name for m in info[0]]
        time.sleep(4)
    return None


def main():
    gc = GameController()
    reader = MemoryReader()

    trio = read_trio(reader, retries=1)
    print(json.dumps({"run": 0, "melodies": trio}), flush=True)

    for i in range(1, N + 1):
        try:
            restart_and_start(gc)
        except Exception as e:
            print(json.dumps({"run": i, "flow_error": str(e)}), flush=True)
            time.sleep(10)
        time.sleep(3)
        trio = read_trio(reader)
        if trio is None:
            # maybe stuck in lobby: try one explicit start
            try:
                start_run(gc)
            except Exception:
                pass
            trio = read_trio(reader)
        print(json.dumps({"run": i, "melodies": trio}), flush=True)


if __name__ == "__main__":
    main()
