"""Shell's way in:
  python3 lib/claude_costing rates <model>   input, output, cache_read and
                                             cache_write_5m in USD per 1M tokens
  python3 lib/claude_costing check [--days N]   reprice local transcripts
                                             against Claude Code's stored totals
  python3 lib/claude_costing sync [--commit SHA] [--from FILE] [--check]
                                             rebuild prices.json from its source
  python3 lib/claude_costing backfill [--dry-run]   reprice stored session records
                                             from this machine's transcripts"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import claude_costing  # noqa: E402


def main(argv):
    if len(argv) == 2 and argv[0] == "rates":
        r = claude_costing.rates(argv[1])
        print(f'{r["input"]:g} {r["output"]:g} {r["cache_read"]:g} {r["cache_write_5m"]:g}')
        return 0
    # Imported on use: sync is the one module that reaches the network.
    if argv and argv[0] == "check":
        from claude_costing import check
        return check.main(argv[1:])
    if argv and argv[0] == "backfill":
        from claude_costing import backfill
        return backfill.main(argv[1:])
    if argv and argv[0] == "sync":
        from claude_costing import sync
        return sync.main(argv[1:])
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
