"""Shell's way in: python3 lib/claude_costing rates <model> prints
input, output, cache_read and cache_write_5m in USD per 1M tokens."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
import claude_costing  # noqa: E402


def main(argv):
    if len(argv) == 2 and argv[0] == "rates":
        r = claude_costing.rates(argv[1])
        print(f'{r["input"]:g} {r["output"]:g} {r["cache_read"]:g} {r["cache_write_5m"]:g}')
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
