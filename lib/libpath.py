"""The one home for how a tool finds lib/: the search order and the line that
runs it. Imported only by its test; stdlib only.

A tool cannot import its way to lib/ before lib/ is on sys.path, so the
search itself must sit in every tool that uses lib/. What has one home is its
text: each tool in bin/ and hooks/ that puts lib/ on sys.path carries BOOTSTRAP
verbatim, and lib/libpath.test.py fails on any other way of doing it. To
change the search, change BOOTSTRAP here, then every copy; the test names each
one still on the old text.

The search: lib/ beside the tool's own directory (a checkout, or the seed
~/.claude links to), then ~/.claude/lib (the seeded copy, for a tool run from
somewhere else). Both go on sys.path, so Python's own import tries them in
that order, module by module; a dir that does not exist costs nothing. Each
tool handles a module it cannot import in its own way (exit, die later, or
fail open), and says it looked in SEARCHED.
"""

BOOTSTRAP = ('sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),\n'
             '                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py')

SEARCHED = "beside the tool and in ~/.claude/lib"
