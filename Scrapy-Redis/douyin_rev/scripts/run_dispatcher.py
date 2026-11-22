# -*- coding: utf-8 -*-
"""只跑 dispatcher（MySQL → Redis），不启爬虫。

用法：
    python scripts/run_dispatcher.py --interval 3
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from douyin_rev.db import init_db                      # noqa: E402
from douyin_rev.tasks import dispatcher, task_state    # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("dispatcher")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--seconds", type=int, default=0, help="跑满 N 秒退出")
    args = ap.parse_args()

    init_db()
    t0 = time.time()
    while True:
        try:
            stat = dispatcher.poll_pending_and_dispatch(limit=args.limit)
            log.info("dispatch: %s", stat)
        except Exception as e:
            log.warning("dispatch 失败: %r", e)
        if args.seconds and time.time() - t0 >= args.seconds:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
