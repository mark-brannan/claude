# Shared shell-text scanner for the PreToolUse gate hooks (no-rm-tree.sh,
# no-git-footguns.sh). Each hook loads it by concatenating this file in front
# of its own awk program: awk "$(cat lib-shell-words.awk)"'<program>'.
# Nothing here decides anything -- it turns the Bash tool's command string
# into words the hook judges.
#
# The hooks are gates, so every ambiguity here resolves toward MORE words
# reaching the hook, never fewer:
#   - an escaped command word (`r\m`, `\git`) becomes the plain word;
#   - a quoted string that holds whitespace stays one unresolvable word ("$Q")
#     AND is queued for a nested scan (texts_of), because `sh -c '...'`,
#     `eval "..."` and `xargs -I{} sh -c '...'` execute exactly that text;
#   - a redirection and its operand are dropped, so `2>&1` is never a target;
#   - a `#` comment is dropped to end of line;
#   - `{` / `}` standing alone are separators (`{ cmd; }`, find's `{}`), but
#     glued to a word they stay in it (`dist{,2}`, `${VAR}`), so brace
#     expansion reaches the hook as a word it can refuse to resolve.
# Anything the scanner gets wrong should therefore surface as a spurious
# word in the hook, i.e. a false deny that names the command, not a bypass.

# Drop every heredoc body: from the end of the line carrying <<WORD to the
# line that is exactly WORD. The marker itself becomes a plain word. Runs on
# the raw text before scan(), so a `<<EOF` inside quotes is stripped too --
# a doc that *mentions* a command is not that command either way.
function strip_heredocs(b,  d, eol, endm, tail, start) {
  while (match(b, /<<-?[ \t]*["']?[A-Za-z_][A-Za-z0-9_]*["']?/)) {
    start = RSTART  # match() below clobbers RSTART; keep the opener's position
    d = substr(b, start, RLENGTH); sub(/^<<-?[ \t]*/, "", d); gsub(/["']/, "", d)
    eol = index(substr(b, start), "\n")
    if (!eol) return substr(b, 1, start - 1) " HEREDOC "
    tail = substr(b, start + eol)
    endm = match(tail, "(^|\n)[ \t]*" d "[ \t]*(\n|$)")
    if (!endm) return substr(b, 1, start - 1) " HEREDOC "
    b = substr(b, 1, start - 1) " HEREDOC " substr(tail, endm + RLENGTH - 1)
  }
  return b
}

# heredoc_bodies(b, bodies): companion to strip_heredocs -- run on the same
# original text, it finds the same heredocs in the same order but returns
# their body text (bodies[1..n]) instead of throwing it away. b itself is
# untouched (awk passes scalars by value).
function heredoc_bodies(b, bodies,   d, eol, endm, tail, start, n) {
  n = 0
  while (match(b, /<<-?[ \t]*["']?[A-Za-z_][A-Za-z0-9_]*["']?/)) {
    start = RSTART
    d = substr(b, start, RLENGTH); sub(/^<<-?[ \t]*/, "", d); gsub(/["']/, "", d)
    eol = index(substr(b, start), "\n")
    if (!eol) return n
    tail = substr(b, start + eol)
    endm = match(tail, "(^|\n)[ \t]*" d "[ \t]*(\n|$)")
    if (!endm) return n
    bodies[++n] = substr(tail, 1, endm - 1)
    b = substr(b, 1, start - 1) " HEREDOC " substr(tail, endm + RLENGTH - 1)
  }
  return n
}

# scan(text, w, k, q): tokenise shell text into w[1..n]; returns n.
#   k[i] == "w"  a word; w[i] is its text after quote removal and escapes.
#   k[i] == "q"  a quoted word containing whitespace; w[i] is "$Q" (a hook
#                can never resolve it) and q[i] is the raw text for texts_of.
# SW_live[i] is 1 when the word carried a `$` or a backtick somewhere the
# shell would act on it -- unquoted or inside double quotes. Inside single
# quotes those are ordinary characters, so a body holding a markdown code
# span or a literal $(...) is text, not substitution, and a hook that
# refuses unresolvable values must not refuse it.
#   k[i] == ";"  a command separator: ; | & newline ( ) ` or a lone { }.
#                Runs of separators collapse to one.
# Also sets SW_shellseg (see sw_mark_shell). Scanner state lives in SW_*
# globals, so a hook must finish with w/k/q before calling scan() again.
function scan(b, w, k, q,   L, i, c, d, n) {
  delete w; delete k; delete q
  delete SW_live
  SW_n = 0; SW_cur = ""; SW_have = 0; SW_quoted = 0; SW_skip = 0; SW_livecur = 0
  L = length(b)
  for (i = 1; i <= L; i++) {
    c = substr(b, i, 1)
    if (c == "\\") {                       # \x is x; \<newline> is nothing
      i++; d = substr(b, i, 1)
      if (d == "\n" || d == "") continue
      SW_cur = SW_cur d; SW_have = 1; continue
    }
    if (c == "'") {                        # literal to the next '
      SW_quoted = 1; SW_have = 1
      d = index(substr(b, i + 1), "'")
      if (!d) { SW_cur = SW_cur substr(b, i + 1); break }
      SW_cur = SW_cur substr(b, i + 1, d - 1); i += d; continue
    }
    if (c == "\"") {                       # \" \\ \$ \` escape; the rest literal
      SW_quoted = 1; SW_have = 1
      for (i++; i <= L; i++) {
        d = substr(b, i, 1)
        if (d == "\"") break
        if (d == "\\" && substr(b, i + 1, 1) ~ /["\\$`]/) { i++; d = substr(b, i, 1) }
        else if (d == "$" || d == "`") SW_livecur = 1
        SW_cur = SW_cur d
      }
      continue
    }
    if (c == "#" && !SW_have) {            # comment to end of line
      d = index(substr(b, i), "\n")
      if (!d) break
      i += d - 2; continue                 # leave the newline for the next pass
    }
    if (c == " " || c == "\t") { sw_emit(w, k, q); continue }
    if (c == "<" || c == ">" || (c == "&" && substr(b, i + 1, 1) == ">")) {
      # A redirection. Drop a bare fd number in front of it (2>&1), the
      # operator, and -- unless it is a dup like >&1 or >&- -- its operand.
      if (SW_have && !SW_quoted && SW_cur ~ /^[0-9]+$/) { SW_cur = ""; SW_have = 0 }
      else sw_emit(w, k, q)
      while (substr(b, i + 1, 1) ~ /[<>|]/) i++
      if (substr(b, i + 1, 1) == "&") {
        i++
        if (substr(b, i + 1, 1) ~ /[0-9-]/) { while (substr(b, i + 1, 1) ~ /[0-9-]/) i++; continue }
      }
      SW_skip = 1; continue
    }
    if (c == ";" || c == "|" || c == "&" || c == "\n" || c == "(" || c == ")" || c == "`") {
      sw_emit(w, k, q); sw_sep(w, k)
      while (substr(b, i + 1, 1) ~ /[;|&]/) i++
      continue
    }
    if ((c == "{" || c == "}") && !SW_have) { sw_sep(w, k); continue }
    if (c == "$") SW_livecur = 1
    SW_cur = SW_cur c; SW_have = 1
  }
  sw_emit(w, k, q)
  sw_mark_shell(w, k, SW_n)
  return SW_n
}

function sw_emit(w, k, q) {
  if (!SW_have) return
  if (SW_skip) SW_skip = 0
  else {
    SW_n++
    if (SW_quoted && SW_cur ~ /[ \t\n]/) { w[SW_n] = "$Q"; k[SW_n] = "q"; q[SW_n] = SW_cur }
    else { w[SW_n] = SW_cur; k[SW_n] = "w" }
    SW_live[SW_n] = SW_livecur
  }
  SW_cur = ""; SW_have = 0; SW_quoted = 0; SW_livecur = 0
}

function sw_sep(w, k) {
  SW_skip = 0
  if (SW_n == 0 || k[SW_n] == ";") return
  SW_n++; w[SW_n] = ";"; k[SW_n] = ";"
}

# Words whose arguments are text, not commands: nothing after them in the
# same segment runs, and a quoted string handed to them is prose. Kept short
# and fail-closed -- an unknown consumer is scanned like an executor. It is
# ignored altogether when some segment of the command is itself a shell
# (`echo "rm -rf x" | sh`), see SW_shellseg.
function sw_prose(t) { return t ~ /^(grep|egrep|fgrep|rg|ag|ack|echo|printf|git|yadm|gh|glab|sed|awk|jq|yq|cat|tee|test|\[|diff|sort|head|tail|wc|tr|cut|less|more)$/ }
# Programs that execute the text they are handed.
function sw_exec(t)  { return t ~ /^(sh|bash|zsh|dash|ksh|ash|busybox|eval|exec|xargs|su|ssh|sudo|doas|env|nohup|timeout|nice|time|watch|parallel|script|chroot|docker|podman|kubectl)$/ }
function sw_shell(t) { return t ~ /^(sh|bash|zsh|dash|ksh|ash|eval|source|\.)$/ }

# seg_cmd(w, k, a, b): index of the command-position word of segment a..b --
# the first word after VAR=x assignments -- or 0.
function seg_cmd(w, k, a, b,   i) {
  for (i = a; i <= b; i++) {
    if (k[i] != "w") return 0
    if (w[i] !~ /^[A-Za-z_][A-Za-z0-9_]*=/) return i
  }
  return 0
}

# sw_mark_shell(w, k, n): sets SW_shellseg when any segment of the scanned
# text is led by a shell, so `echo ... | sh` is executed text, not prose.
function sw_mark_shell(w, k, n,   a, i, c) {
  SW_shellseg = 0; a = 1
  for (i = 1; i <= n + 1; i++) {
    if (i <= n && k[i] != ";") continue
    c = seg_cmd(w, k, a, i - 1)
    if (c && sw_shell(w[c])) { SW_shellseg = 1; return }
    a = i + 1
  }
}

# texts_of(text, texts, nested): the text itself plus, recursively, every
# quoted string in it that holds whitespace and may run -- the body of a
# `sh -c`, an `eval`, an `xargs sh -c`, an argument to a program this
# library does not know. Skipped only when the segment is led by a prose
# consumer (sw_prose), holds no executor (sw_exec) and no segment of the
# text is a shell. Returns the count; nested[x] is 1 for the quoted ones,
# which the hooks judge by command position only. Capped so a pathological
# command cannot spin.
function texts_of(text, texts, nested,   x, cnt, n, i, j, a, c, ex, w, k, q) {
  texts[1] = text; nested[1] = 0; cnt = 1
  for (x = 1; x <= cnt && cnt < 64; x++) {
    n = scan(texts[x], w, k, q)
    a = 1
    for (i = 1; i <= n + 1; i++) {
      if (i <= n && k[i] != ";") continue
      c = seg_cmd(w, k, a, i - 1)
      ex = SW_shellseg
      if (!ex) for (j = a; j < i; j++) if (k[j] == "w" && sw_exec(w[j])) { ex = 1; break }
      if (ex || !c || !sw_prose(w[c]))
        for (j = a; j < i && cnt < 64; j++) if (k[j] == "q") { cnt++; texts[cnt] = q[j]; nested[cnt] = 1 }
      a = i + 1
    }
  }
  return cnt
}

# cmd_index(w, k, a, b, re, nested, parents): index in a..b of the word that
# is the command `re` describes, or 0.
#   Top level (nested == 0): ANY word matching re counts, wherever it stands
#   -- `find .. -exec rm`, `xargs rm`, `do rm`, `time rm` all run rm --
#   unless the word before it matches `parents` (`git rm` is git's
#   subcommand), or the segment is led by a prose consumer (`echo rm -rf x`
#   prints) and no segment of the text is a shell. An unknown wrapper
#   therefore yields a check, not a bypass.
#   Nested text (nested == 1): only the command position counts -- the first
#   word after VAR=x assignments, wrappers with their options, and shell
#   keywords. `sh -c 'rm -rf x'` is caught; a commit message that mentions
#   `rm -rf x` mid-sentence is not.
function cmd_index(w, k, a, b, re, nested, parents,   i, wrap, c) {
  if (!nested) {
    c = seg_cmd(w, k, a, b)
    for (i = a; i <= b; i++) {
      if (k[i] == "w" && w[i] ~ re &&
          !(i > a && k[i - 1] == "w" && parents != "" && w[i - 1] ~ parents)) return i
      if (i == c && sw_prose(w[c]) && !SW_shellseg) return 0
    }
    return 0
  }
  wrap = 0
  for (i = a; i <= b; i++) {
    if (k[i] != "w") return 0
    if (w[i] ~ re) return i
    if (w[i] ~ /^[A-Za-z_][A-Za-z0-9_]*=/) continue
    if (w[i] ~ /^(sudo|env|command|exec|time|nice|nohup|timeout|doas|builtin|if|then|else|elif|while|until|do|!)$/) { wrap = 1; continue }
    if (wrap && (w[i] ~ /^-/ || w[i] ~ /^[0-9]+[smhd]?$/)) continue
    return 0
  }
  return 0
}

# sw_writes(text, out, heredoc_only): the file paths `text` writes with a
# redirection or `tee` -- `> f`, `>> f`, `tee f`. Returns the count.
#
# Heredoc bodies are skipped, using strip_heredocs' own delimiter matching:
# a `<<` inside a body is body text, not shell syntax, and a scanner that
# missed that would let attacker-controlled content name any path it liked.
# With heredoc_only == 1 only the targets of lines that OPEN a heredoc come
# back -- the paths whose content is the heredoc body.
#
# A hook that reads a file an argument names can use the pair to tell "the
# file is not there" from "the file is not there YET, and its content is the
# heredoc body I am already scanning". That second reading holds only while
# the heredoc is the one and only write to that path, so a caller must check
# the path's count in the unrestricted result too: `> f <<EOF ... EOF; echo
# private >> f` writes twice, and the second write is not the body.
#
# Quotes are stripped; a path built from $VAR comes back unresolved, so a
# caller comparing paths simply will not match it.
function sw_writes(b, out, heredoc_only,   nl, lines, i, line, pre, nt, t, x, teeing, n, delim, opens) {
  delete out; n = 0; delim = ""
  nl = split(b, lines, "\n")
  for (i = 1; i <= nl; i++) {
    line = lines[i]
    if (delim != "") {                       # inside a heredoc body: not shell
      if (line ~ ("^[ \t]*" delim "[ \t]*$")) delim = ""
      continue
    }
    opens = match(line, /<<-?[ \t]*["\047]?[A-Za-z_][A-Za-z0-9_]*["\047]?/)
    if (opens) {
      delim = substr(line, RSTART, RLENGTH)
      sub(/^<<-?[ \t]*/, "", delim); gsub(/["\047]/, "", delim)
      pre = substr(line, 1, RSTART - 1)      # only what stands before the <<
    } else pre = line
    if (heredoc_only && !opens) continue
    gsub(/[;|&]/, " ; ", pre)
    gsub(/>>?/, " @redir@ ", pre)            # not "&": in gsub that means the match
    nt = split(pre, t, /[ \t]+/)
    teeing = 0
    for (x = 1; x <= nt; x++) {
      if (t[x] == ";") { teeing = 0; continue }
      if (t[x] == "@redir@") {
        if (x < nt && t[x + 1] != ";" && t[x + 1] != "@redir@") out[++n] = sw_unq(t[x + 1])
        continue
      }
      if (sw_unq(t[x]) == "tee") { teeing = 1; continue }
      if (teeing && t[x] !~ /^-/) out[++n] = sw_unq(t[x])
    }
  }
  return n
}
function sw_unq(t) { gsub(/["\047]/, "", t); return t }
