"""lanes_html(db_path): the metrics dashboard's multi-lane view on one time axis.
Keystroke rate, clicks and scroll, decisions and friction against the unbroken
stretch since your last break, and sessions with their API-equivalent cost, with a
1 / 3 / 7 / 30 day range per CSS radio. Reads metrics.db read-only; stdlib only;
returns an HTML fragment (inline SVG, no scripts) styled by the dashboard's CSS
variables, every rule under .lanes."""
import bisect, collections, datetime as dt, html, math, sqlite3

BREAK = 5          # minutes: a gap over this ends a stretch of work
AWAY = 3 * 3600    # seconds: a gap this long is sleep or away
RANGES = [("1 day", 86400, 300, "5 min"), ("3 days", 3 * 86400, 900, "15 min"),
          ("7 days", 7 * 86400, 3600, "1 hour"), ("30 days", 30 * 86400, 7200, "2 hours")]
W, L, R, T, B, LH = 900, 44, 44, 10, 4, 96
PAL = ["--s1", "--s2", "--bad", "--s3", "--ink2", "--good", "--muted"]

CSS = """.lanes .rg { position:absolute; opacity:0; pointer-events:none }
.lanes .rt { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 }
.lanes .rt label { padding:5px 12px; border-radius:99px; background:var(--surface); border:1px solid var(--grid); cursor:pointer; font-size:13px }
.lanes .rp { display:none } .lanes svg.ch { width:100%; height:auto; display:block }
.lanes .g { stroke:var(--grid); stroke-width:1 } .lanes .g2 { stroke:var(--grid); stroke-width:1; opacity:.5 }
.lanes .t, .lanes .t2 { font-size:10px; fill:var(--muted) } .lanes .ln { font-size:11px; fill:var(--ink); font-weight:600 }
.lanes .br { fill:var(--s2); opacity:.14 } .lanes .sl { fill:var(--ink2); opacity:.22 }
""" + "".join(f".lanes #lr{i}:checked ~ .rt label[for=lr{i}] {{ border-color:var(--s1); color:var(--ink) }} "
               f".lanes #lr{i}:checked ~ #lp{i} {{ display:block }}\n" for i in range(len(RANGES)))


def _pct(v, q):
    v = sorted(v); i = (len(v) - 1) * q; lo = int(i); hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def _ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


class _Ch:
    def __init__(s, n, ymax, h, ymax2=None):
        s.n, s.y1, s.h, s.p = n, (ymax or 1) * 1.1, h, []
    def X(s, x): return L + (W - L - R) * x / (s.n or 1)
    def Y(s, y): return T + (s.h - T - B) * (1 - y / s.y1)
    def grid(s, vals, fmt):
        for v in vals:
            s.p.append(f'<line x1="{L}" x2="{W-R}" y1="{s.Y(v):.1f}" y2="{s.Y(v):.1f}" class="g"/>'
                       f'<text x="{L-5}" y="{s.Y(v)+3:.1f}" class="t" text-anchor="end">{fmt(v)}</text>')
    def line(s, pts, i, w=1.8, op=1):
        if len(pts) < 2: return
        d = "M" + " L".join(f"{s.X(x):.1f},{s.Y(y):.1f}" for x, y in pts)
        s.p.append(f'<path d="{d}" fill="none" stroke="var({PAL[i]})" stroke-width="{w}" stroke-linejoin="round" opacity="{op}"/>')
    def bars(s, pts, i, bw):
        b = s.Y(0)
        for x, y in pts:
            s.p.append(f'<rect x="{s.X(x)-bw/2:.1f}" y="{min(s.Y(y), b):.1f}" width="{bw:.1f}" height="{abs(b-s.Y(y)):.1f}" fill="var({PAL[i]})" opacity=".55"/>')


def _load(db_path):
    cx = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        act = cx.execute("select minute*60, sum(keys), sum(clicks), sum(scroll) from input "
                         "where afk=0 group by minute order by minute").fetchall()
        sess = []
        for sa, ts, ea, cost in cx.execute(
                "select started_at, ts, ended_at, (select sum(cost_usd) from session_cost c where c.session_id=s.session_id) from sessions s"):
            try:
                a = _ts(sa or ts); b = _ts(ea) if ea else a + 60
            except Exception:
                continue
            sess.append((a, max(b, a + 60), cost or 0))
        def ev(sql):
            out = []
            for (t,) in cx.execute(sql):
                try: out.append(_ts(t))
                except Exception: pass
            return sorted(out)
        return act, sess, ev("select ts from friction where retracted=0"), ev("select ts from decisions")
    finally:
        cx.close()


def lanes_html(db_path):
    act, sess, fts, dts = _load(db_path)
    if not act:
        return '<div class="lanes"><p class="note">No keyboard and mouse minutes recorded yet.</p></div>'
    end = act[-1][0] + 60
    # streak = minutes since the last gap over BREAK; gaps are shaded
    streak, gaps, run, prev = {}, [], 0, None
    for m in (r[0] // 60 for r in act):
        run = run + 1 if prev is not None and m - prev <= BREAK else 1
        if prev is not None and m - prev > BREAK: gaps.append((prev * 60 + 60, m * 60))
        streak[m] = run; prev = m
    RES = sorted(m * 60 for m, v in streak.items() if v == 1)

    def saw(ev, start, bk, nb):  # events since the last break, at each bucket's end
        out = []
        for i in range(nb):
            te = start + (i + 1) * bk; k = bisect.bisect_right(RES, te) - 1; lr = RES[k] if k >= 0 else 0
            out.append(bisect.bisect_right(ev, te) - bisect.bisect_left(ev, lr))
        return out

    def build(span, bk):
        start = end - span; nb = span // bk; x = lambda t: (t - start) / bk
        bix = lambda t: int((t - start) // bk) if start <= t < end else None
        KM = [[] for _ in range(nb)]; C = [0] * nb; Sc = [0] * nb; WK = [0] * nb
        A = [0] * nb; CO = [0.0] * nb; DE = [0] * nb; FR = [0] * nb
        for t, k, cl, sc in act:
            b = bix(t)
            if b is not None:
                C[b] += cl; Sc[b] += sc
                if k > 0: KM[b].append(k)  # keys in one active minute = a per-minute rate
        for m, v in streak.items():
            b = bix(m * 60)
            if b is not None: WK[b] = max(WK[b], v)
        for arr, ev in ((FR, fts), (DE, dts)):
            for t in ev:
                b = bix(t)
                if b is not None: arr[b] += 1
        for a, b2, usd in sess:  # cost is spread evenly over each session's run (an assumption)
            lo, hi = max(a, start), min(b2, end)
            for b in range(int((lo - start) // bk), min(nb, int((hi - start) // bk) + 1)) if hi > lo else ():
                bs = start + b * bk; ov = min(hi, bs + bk) - max(lo, bs)
                if ov > 0: A[b] += 1; CO[b] += usd * ov / (b2 - a)
        HS = [LH + 34, LH + 34, LH, LH + 10]; YS = [sum(HS[:i]) for i in range(4)]; Ht = sum(HS) + 22
        out = [f'<svg viewBox="0 0 {W} {Ht}" class="ch">']
        step = {86400: 3 * 3600, 3 * 86400: 12 * 3600, 7 * 86400: 86400, 30 * 86400: 5 * 86400}[span]
        ticks, t = [], math.ceil(start / step) * step
        while t < end:
            d = dt.datetime.fromtimestamp(t)
            ticks.append((x(t), d.strftime("%a %-d %H:%M") if step < 86400 else d.strftime("%b %-d"))); t += step
        def lane(i, name, fn, ymax, fmt, ymax2=None, fmt2=None):
            h = HS[i]; ch = _Ch(nb, ymax, h); ch2 = _Ch(nb, ymax2, h)
            for xt, _ in ticks: ch.p.append(f'<line x1="{ch.X(xt):.1f}" x2="{ch.X(xt):.1f}" y1="{T}" y2="{h-B}" class="g2"/>')
            for a, b2 in gaps:
                if (b2 - a >= AWAY or (span < 7 * 86400 and b2 - a > BREAK * 60)) and b2 > start and a < end:
                    xa = ch.X(max(0, x(a))); xb = ch.X(min(nb, x(b2)))
                    ch.p.append(f'<rect x="{xa:.1f}" y="{T}" width="{max(1, xb-xa):.1f}" height="{h-T-B}" class="{"sl" if b2-a >= AWAY else "br"}"/>')
            ch.grid([0, ymax or 1], fmt)
            if ymax2:
                for v in (0, ymax2): ch.p.append(f'<text x="{W-R+2}" y="{ch2.Y(v)+3:.1f}" class="t2">{fmt2(v)}</text>')
            fn(ch, ch2)
            out.append(f'<g transform="translate(0,{YS[i]})"><text x="{L}" y="9" class="ln">{name}</text>{"".join(ch.p)}{"".join(ch2.p)}</g>')
        ctr = lambda arr: [(i + .5, v) for i, v in enumerate(arr)]
        bw = max(1.5, (W - L - R) / nb * .8)
        MX = [max(v) if v else 0 for v in KM]
        def inp(ch, _):
            ch.line(ctr(MX), 0, 1.8)  # sawtooth: peak minute in each bucket
            ch.line(ctr([_pct(v, .9) if v else 0 for v in KM]), 4, 1.2)
            ch.line(ctr([sum(v) / len(v) if v else 0 for v in KM]), 1, 1.6)
            ch.line(ctr([_pct(v, .5) if v else 0 for v in KM]), 3, 1.2)
        lane(1, "Keystrokes per minute, over active minutes in each bucket: max (blue, bold) · p90 (grey) · mean (orange) · p50 (teal)",
             inp, max(MX) or 1, lambda v: f"{v:,.0f}/min")
        lane(2, "Clicks (orange) · scroll (teal)", lambda ch, _: (ch.line(ctr(C), 1, 1.5), ch.line(ctr(Sc), 3, 1.5)),
             max(max(C), max(Sc)) or 1, lambda v: f"{v:,.0f}")
        DS, FS = saw(dts, start, bk, nb), saw(fts, start, bk, nb); wm = max(WK) or 1
        def df(ch, ch2):
            d = "M" + " L".join(f"{ch2.X(xx):.1f},{ch2.Y(y):.1f}" for xx, y in [(0, 0)] + ctr(WK) + [(nb, 0)]) + "Z"
            ch.p.insert(0, f'<path d="{d}" fill="var(--s2)" opacity=".16"/>')
            ch.line(ctr(DE), 6, 1, .35); ch.line(ctr(FR), 2, 1, .35); ch.line(ctr(DS), 6, 1.9); ch.line(ctr(FS), 2, 2.1)
        lane(0, "Decisions (grey) · friction (red): bold = running count since your last break, thin = count in the bucket · orange fill: minutes since last break",
             df, max(DS + FS + DE + FR) or 1, lambda v: f"{v:g}", wm, lambda v: f"{v:g}m")
        lane(3, "Sessions running (line, left axis) · API-equivalent $ (green bars, right axis, spread over each session's run)",
             lambda ch, ch2: (ch2.bars(ctr(CO), 5, bw), ch.line(ctr(A), 1, 1.8)),
             max(A) or 1, lambda v: f"{v:g}", max(CO) or 1, lambda v: f"${v:,.0f}")
        for xt, lab in ticks: out.append(f'<text x="{L + (W-L-R)*xt/nb:.1f}" y="{Ht-6}" class="t" text-anchor="middle">{lab}</text>')
        return "".join(out) + "</svg>"

    radios = "".join(f'<input type="radio" class="rg" name="lanes-range" id="lr{i}"{" checked" if i == 1 else ""}>' for i in range(len(RANGES)))
    tabs = "".join(f'<label for="lr{i}">{n} <small>· {b}</small></label>' for i, (n, _, _, b) in enumerate(RANGES))
    panels = "".join(f'<div class="rp" id="lp{i}">{build(s, b)}</div>' for i, (_, s, b, _) in enumerate(RANGES))
    return (f'<div class="lanes"><style>{CSS}</style><p class="note">One time axis; each range sets its bucket size. Orange bands are breaks '
            f'over {BREAK} minutes (1 and 3 day views); grey bands are gaps of {AWAY // 3600} hours or more, sleep or away. Local time, newest at the right.</p>'
            f'{radios}<div class="rt">{tabs}</div>{panels}</div>')
