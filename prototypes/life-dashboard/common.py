# Prototype of a life-first dashboard. Read-only on metrics.db; writes one HTML file. Not part of PR 424.
"""Shared data load and SVG helpers for the life-first dashboard pages.
Read-only on metrics.db. Importing this module reads the database."""
import sqlite3, datetime as dt, html, os, collections
from pathlib import Path
from zoneinfo import ZoneInfo
DB=os.environ.get("LIFE_DASHBOARD_DB") or str(Path.home()/"claude_prompts_scratch/state/global/metrics/dashboard/metrics.db")
BREAK=5            # minutes: a gap over this ends a stretch of work; one definition for the counts, the bands and the captions
AWAY=3*3600        # seconds: a gap this long is sleep or away
c=sqlite3.connect(f"file:{DB}?mode=ro",uri=True); c.row_factory=sqlite3.Row
def _zone():
    try: return ZoneInfo(os.environ.get("TZ") or os.path.realpath("/etc/localtime").split("zoneinfo/",1)[1])
    except Exception: return dt.datetime.now().astimezone().tzinfo   # fixed offset: no DST handling
TZ=_zone()
def loc(sec): return dt.datetime.fromtimestamp(sec,TZ)
def iso(ts): return dt.datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(TZ)
SHIFT=dt.timedelta(hours=4)          # a day runs 4am to 4am, so a night owl stays one day
def dayof(t): return (t-SHIFT).date()
rows=[(r["minute"]*60,r["keys"],r["clicks"],r["scroll"],r["move"],r["afk"]) for r in c.execute("select minute,keys,clicks,scroll,move,afk from input order by minute")]
act=[r for r in rows if not r[5]]
if not act: raise SystemExit(f"no input rows in {DB}")
byday=collections.defaultdict(list)
for r in act: byday[dayof(loc(r[0]))].append(r)
days=sorted(byday); D0,D1=days[0],days[-1]
alld=[D0+dt.timedelta(i) for i in range((D1-D0).days+1)]
def hrs(t): h=(t-SHIFT); return 4+h.hour+h.minute/60   # clock hour, 4..28
first={};last={};keys={};hh={};longest={}
for d in alld:
    rs=byday.get(d,[])
    if not rs: continue
    ts=[loc(r[0]) for r in rs]; first[d]=hrs(min(ts)); last[d]=hrs(max(ts))
    keys[d]=sum(r[1] for r in rs); hh[d]=len(rs)/60
    run=best=1; m=[r[0]//60 for r in rs]
    for a,b in zip(m,m[1:]):
        run=run+1 if b-a<=BREAK else 1; best=max(best,run)
    longest[d]=best/60
# --- claude side
S=[dict(r) for r in c.execute("select ts,started_at,ended_at,model,cost_usd,fr_total,dec_total,commits from sessions")]
fr_d=collections.Counter(); dec_d=collections.Counter(); cost_d=collections.Counter(); cost_m=collections.defaultdict(collections.Counter)
for s in S:
    try: t=iso(s["started_at"] or s["ts"])
    except Exception: continue
    d=dayof(t); fr_d[d]+=s["fr_total"] or 0; dec_d[d]+=s["dec_total"] or 0
def short(m): return (m or "?").replace("claude-","").split("-2")[0]
for r in c.execute("select s.started_at,s.ts,sc.model,sc.cost_usd from session_cost sc join sessions s on s.session_id=sc.session_id"):
    try: t=iso(r["started_at"] or r["ts"])
    except Exception: continue
    cost_d[dayof(t)]+=r["cost_usd"] or 0; mon=dayof(t); mon=mon-dt.timedelta(mon.weekday()); cost_m[short(r["model"])][mon]+=r["cost_usd"] or 0
# --- svg helpers
W,H=900,200; L,R,T,B=44,44,14,26
def pal(i): return f"var(--c{i})"
class Ch:
    def __init__(s,x0,x1,y0,y1,h=H,ylab=""):
        s.x0,s.x1,s.y0,s.y1,s.h=x0,x1,y0,y1,h; s.p=[]; s.ylab=ylab
    def X(s,x): return L+(W-L-R)*(x-s.x0)/((s.x1-s.x0) or 1)
    def Y(s,y): return T+(s.h-T-B)*(1-(y-s.y0)/((s.y1-s.y0) or 1))
    def grid(s,yt,fmt=lambda v:f"{v:g}"):
        for v in yt: s.p.append(f'<line x1="{L}" x2="{W-R}" y1="{s.Y(v):.1f}" y2="{s.Y(v):.1f}" class="g"/><text x="{L-5}" y="{s.Y(v)+3:.1f}" class="t" text-anchor="end">{fmt(v)}</text>')
    def xt(s,ticks):
        for x,l in ticks: s.p.append(f'<text x="{s.X(x):.1f}" y="{s.h-8}" class="t" text-anchor="middle">{l}</text><line x1="{s.X(x):.1f}" x2="{s.X(x):.1f}" y1="{T}" y2="{s.h-B}" class="g2"/>')
    def line(s,pts,i,w=1.8,dash=None,op=1):
        pts=[(x,y) for x,y in pts if y is not None]
        if len(pts)<2: return
        d="M"+" L".join(f"{s.X(x):.1f},{s.Y(y):.1f}" for x,y in pts)
        s.p.append(f'<path d="{d}" fill="none" stroke="{pal(i)}" stroke-width="{w}" stroke-linejoin="round" {"stroke-dasharray=%s"%chr(34)+dash+chr(34) if dash else ""} opacity="{op}"/>')
    def bars(s,pts,i,bw,op=.55,base=None):
        b=s.Y(max(s.y0,0) if base is None else base)
        for x,y in pts:
            if y is None: continue
            s.p.append(f'<rect x="{s.X(x)-bw/2:.1f}" y="{min(s.Y(y),b):.1f}" width="{bw:.1f}" height="{abs(b-s.Y(y)):.1f}" fill="{pal(i)}" opacity="{op}"/>')
    def svg(s): return f'<svg viewBox="0 0 {W} {s.h}" class="ch">{"".join(s.p)}</svg>'
def trail(series,n=7):   # trailing mean over n days, ignoring missing
    out=[]
    for i,d in enumerate(alld):
        w=[series.get(alld[j]) for j in range(max(0,i-n+1),i+1)]; w=[v for v in w if v is not None]
        out.append((i,sum(w)/len(w) if w else None))
    return out
def dticks(): 
    return [(i,alld[i].strftime("%b %-d")) for i in range(0,len(alld),max(1,len(alld)//9))]
def legend(items): return '<div class="lg">'+"".join(f'<span><i style="background:{pal(i)}"></i>{html.escape(n)}</span>' for i,n in items)+'</div>'
def sect(title,sub,body,note=""): return f'<section><h2>{html.escape(title)}</h2><p class="sub">{sub}</p>{body}{f"<p class=note>{note}</p>" if note else ""}</section>'
CSS='''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Life dashboard</title><style>
:root{--bg:#fff;--fg:#1c1c1e;--mut:#6b6b70;--card:#f5f5f7;--g:#e4e6eb;--c0:#3b6fb6;--c1:#d9822b;--c2:#d1453b;--c3:#2f9e8f;--c4:#7a5bb5;--c5:#3a9a4f;--c6:#555}
@media(prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececef;--mut:#9a9aa2;--card:#1d1d21;--g:#2c2e35;--c0:#6fa3ec;--c1:#f0a255;--c2:#ef6b5f;--c3:#55c7b6;--c4:#a98bea;--c5:#5ccf75;--c6:#b5b5bd}}
body{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:960px;padding:14px 16px 60px}
h1{font-size:20px;margin:0 0 2px}h2{font-size:16px;margin:0}section{background:var(--card);border-radius:12px;padding:12px 14px;margin:14px 0}
.sub{color:var(--mut);margin:2px 0 8px;font-size:13px}.note{margin:6px 0 0;font-size:13px}.band{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);margin:26px 0 -6px}
svg.ch{width:100%;height:auto;display:block}.t{font-size:10px;fill:var(--mut)}.g{stroke:var(--g);stroke-width:1}.g2{stroke:var(--g);stroke-width:1;opacity:.5}.mid{stroke:var(--mut);stroke-dasharray:4 3;stroke-width:1}
.lg{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--mut);margin:4px 0}.lg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
</style>'''
