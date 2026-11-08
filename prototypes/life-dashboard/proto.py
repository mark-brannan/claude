#!/usr/bin/env python3
# Prototype of a life-first dashboard. Read-only on metrics.db; writes one HTML file. Not part of PR 424.
import sqlite3, datetime as dt, html, sys, collections, statistics as st
DB="/home/solace/claude_prompts_scratch/state/global/metrics/dashboard/metrics.db"
OUT=sys.argv[1]
c=sqlite3.connect(f"file:{DB}?mode=ro",uri=True); c.row_factory=sqlite3.Row
TZ=dt.datetime.now().astimezone().tzinfo
def loc(sec): return dt.datetime.fromtimestamp(sec,TZ)
def iso(ts): return dt.datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(TZ)
SHIFT=dt.timedelta(hours=4)          # a day runs 4am to 4am, so a night owl stays one day
def dayof(t): return (t-SHIFT).date()
rows=[(r["minute"]*60,r["keys"],r["clicks"],r["scroll"],r["move"],r["afk"]) for r in c.execute("select minute,keys,clicks,scroll,move,afk from input order by minute")]
act=[r for r in rows if not r[5]]
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
        run=run+1 if b-a<=5 else 1; best=max(best,run)
    longest[d]=best/60
# --- claude side
S=[dict(r) for r in c.execute("select ts,started_at,model,cost_usd,fr_total,dec_total,commits from sessions")]
fr_d=collections.Counter(); dec_d=collections.Counter(); cost_d=collections.Counter(); cost_m=collections.defaultdict(collections.Counter)
for s in S:
    try: t=iso(s["started_at"] or s["ts"])
    except Exception: continue
    d=dayof(t); fr_d[d]+=s["fr_total"] or 0; dec_d[d]+=s["dec_total"] or 0; cost_d[d]+=s["cost_usd"] or 0
def short(m): return (m or "?").replace("claude-","").split("-2")[0]
for r in c.execute("select s.started_at,s.ts,sc.model,sc.cost_usd from session_cost sc join sessions s on s.session_id=sc.session_id"):
    try: t=iso(r["started_at"] or r["ts"])
    except Exception: continue
    mon=dayof(t); mon=mon-dt.timedelta(mon.weekday()); cost_m[short(r["model"])][mon]+=r["cost_usd"] or 0
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
secs=[]
N=len(alld)
# 1 day shape
ch=Ch(0,N-1,4,28)
ch.grid([4,8,12,16,20,24,28],lambda v:f"{int(v%24):02d}:00"); ch.xt(dticks())
for i,d in enumerate(alld):
    if d in first: ch.p.append(f'<rect x="{ch.X(i)-4:.1f}" y="{ch.Y(last[d]):.1f}" width="8" height="{ch.Y(first[d])-ch.Y(last[d]):.1f}" rx="2" fill="{pal(0)}" opacity=".45"/>')
ch.line([(i,last.get(d)) for i,d in enumerate(alld)],2,2)
ch.p.append(f'<line x1="{L}" x2="{W-R}" y1="{ch.Y(24):.1f}" y2="{ch.Y(24):.1f}" class="mid"/><text x="{W-R}" y="{ch.Y(24)-3:.1f}" class="t" text-anchor="end">midnight</text>')
lastn=[last[d] for d in alld[-7:] if d in last]; late=sum(1 for d in last if last[d]>=24)
secs.append(sect("Your days: when they start and end","Each bar runs from first to last input of a day (days turn over at 4am). The red line follows the last input.",
  ch.svg()+legend([(0,"first to last input"),(2,"last input")]),
  f"Latest last-input in the past 7 days: {int(max(lastn)%24):02d}:{int(max(lastn)%1*60):02d}. {late} of {len(last)} days since {D0:%b %-d} ran past midnight (measured)."))
# 2 hours & breaks
hmax=max(max(hh.values()),max(longest.values()))
ch=Ch(0,N-1,0,hmax*1.08); ch.grid([v for v in range(0,int(hmax)+1,2)],lambda v:f"{v:g}h"); ch.xt(dticks())
ch.bars([(i,hh.get(d)) for i,d in enumerate(alld)],0,8); ch.line([(i,longest.get(d)) for i,d in enumerate(alld)],3,2)
ch.line(trail(hh),1,2,"5 3")
secs.append(sect("Time at the keyboard, and the longest stretch without a break","Bars: hours with input. Orange: longest stretch with no gap over 5 minutes. Dashed: 7-day average of hours.",
  ch.svg()+legend([(0,"hours with input"),(3,"longest unbroken stretch"),(1,"7-day average hours")]),
  f"7-day average {sum(v for _,v in trail(hh)[-1:])/1:.1f} h/day; longest unbroken stretch in the window {max(longest.values()):.1f} h (measured)."))
# 3 keystrokes/day
kmax=max(keys.values())
ch=Ch(0,N-1,0,kmax*1.08); ch.grid([int(kmax*f/4) for f in range(5)],lambda v:f"{v/1000:.0f}k"); ch.xt(dticks())
ch.bars([(i,keys.get(d)) for i,d in enumerate(alld)],4,8); ch.line(trail(keys),1,2,"5 3")
secs.append(sect("Keystrokes per day","Bars: keys pressed that day. Dashed: 7-day average.",ch.svg()+legend([(4,"keystrokes"),(1,"7-day average")]),
  f"{sum(keys.values()):,} keys over {len(keys)} days with input (measured)."))
# 4 overlay: last 3 days, 15-minute buckets
end=max(r[0] for r in rows); WIN=3*86400; start=end-WIN; BK=900
nb=WIN//BK
agg=[[0,0,0,0] for _ in range(nb)]
for t,k,cl,sc,mv,afk in act:
    if t>=start:
        b=min(nb-1,(t-start)//BK); a=agg[b]; a[0]+=k; a[1]+=cl; a[2]+=sc; a[3]+=mv
def evb(rows_,key):
    o=collections.Counter()
    for r in rows_:
        t=iso(r[key]).timestamp()
        if t>=start: o[int(min(nb-1,(t-start)//BK))]+=1
    return o
fev=evb(c.execute("select ts from friction where retracted=0").fetchall(),0)
dev=evb(c.execute("select ts from decisions").fetchall(),0)
cev=evb(c.execute("select ts from commits").fetchall(),0)
ser=[("keys",0,0),("clicks",1,3),("scroll",2,4)]
# normalise: each series as % of its own busiest 15 minutes, so shapes share one axis
ch=Ch(0,nb,0,100,h=260); ch.grid([0,25,50,75,100],lambda v:f"{v:g}%")
tk=[]
for i in range(0,nb+1,8):
    t=loc(start+i*BK); tk.append((i,t.strftime("%a %H:%M") if t.hour==0 or i==0 else t.strftime("%H:%M")))
tk=[(i,l) for i,l in tk][::2]; ch.xt(tk)
mx={}
for n,j,col in ser:
    m=max(a[j] for a in agg) or 1; mx[n]=m
    ch.line([(i+.5,100*agg[i][j]/m) for i in range(nb)],col,1.7)
bars_lane=""
lane=Ch(0,nb,0,3,h=110); lane.xt([]); 
for k,(n,ev,col) in enumerate([("friction",fev,2),("decisions",dev,1),("commits",cev,5)]):
    y=k+.5
    lane.p.append(f'<text x="{L-5}" y="{lane.Y(y)+3:.1f}" class="t" text-anchor="end">{n}</text><line x1="{L}" x2="{W-R}" y1="{lane.Y(y):.1f}" y2="{lane.Y(y):.1f}" class="g"/>')
    for i,v in ev.items(): lane.p.append(f'<circle cx="{lane.X(i+.5):.1f}" cy="{lane.Y(y):.1f}" r="{min(2+1.4*v,9):.1f}" fill="{pal(col)}" opacity=".75"/>')
fr_n=sum(fev.values()); dec_n=sum(dev.values()); cm=sum(cev.values())
secs.append(sect("The last three days, every 15 minutes","Keys, clicks and scroll on one time axis, each scaled to its own busiest 15 minutes (100%). Below, the same axis: when friction, decisions and commits landed; bigger dot, more in that window.",
  ch.svg()+legend([(0,f"keys (peak {mx['keys']:,}/15 min)"),(3,f"clicks (peak {mx['clicks']:,})"),(4,f"scroll (peak {mx['scroll']:,})")])+lane.svg(),
  f"{fr_n} friction events, {dec_n} decisions, {cm} commits in these three days (measured). Prompts have no timestamp in metrics.db, only a count per session, so they are not on this chart."))
# 5 claude: friction/h daily + trailing
frh={d:(fr_d[d]/hh[d]) for d in alld if d in hh and hh[d]>=1}
fm=max(frh.values())
ch=Ch(0,N-1,0,fm*1.08); ch.grid([round(fm*f/4,1) for f in range(5)],lambda v:f"{v:.1f}"); ch.xt(dticks())
ch.bars([(i,frh.get(d)) for i,d in enumerate(alld)],2,8,.35); ch.line(trail(frh),2,2.2)
dh={d:(dec_d[d]/hh[d]) for d in alld if d in hh and hh[d]>=1}
dm=max(dh.values()); ch2=Ch(0,N-1,0,dm*1.08); ch2.grid([round(dm*f/4,1) for f in range(5)],lambda v:f"{v:.1f}"); ch2.xt(dticks())
ch2.bars([(i,dh.get(d)) for i,d in enumerate(alld)],1,8,.35); ch2.line(trail(dh),1,2.2)
t7f=trail(frh)[-1][1]; pk3=max([frh[d] for d in alld[-3:] if d in frh] or [0])
t7d=trail(dh)[-1][1]
secs.append(sect("Friction per keyboard hour","Bars: each day (days with under an hour of input left out). Line: 7-day trailing average.",
  ch.svg()+legend([(2,"daily"),(2,"7-day trailing (line)")]),f"Trailing 7-day {t7f:.1f}/h · worst of the last 3 days {pk3:.1f}/h (measured, from a friction detector I have not validated)."))
secs.append(sect("Decisions per keyboard hour","Same construction.",ch2.svg(),f"Trailing 7-day {t7d:.1f}/h (measured)."))
# 6 cost
cm_s=sorted(cost_m,key=lambda m:-sum(cost_m[m].values())); top=cm_s[:3]; rest=cm_s[3:]
weeks=sorted({w for m in cost_m for w in cost_m[m]}); weeks=[w for w in weeks if w>=D0-dt.timedelta(60)]
stack=[(m,[cost_m[m].get(w,0) for w in weeks]) for m in top]
if rest: stack.append(("other",[sum(cost_m[m].get(w,0) for m in rest) for w in weeks]))
tot=[sum(s[1][i] for s in stack) for i in range(len(weeks))]; cmx=max(tot) or 1
ch=Ch(0,len(weeks)-1,0,cmx*1.08); ch.grid([round(cmx*f/4,-1) for f in range(5)],lambda v:f"${v:,.0f}")
ch.xt([(i,weeks[i].strftime("%b %-d")) for i in range(0,len(weeks),2)])
base=[0]*len(weeks)
for k,(m,v) in enumerate(stack):
    top_=[base[i]+v[i] for i in range(len(weeks))]
    pts=[(i,top_[i]) for i in range(len(weeks))]+[(i,base[i]) for i in range(len(weeks)-1,-1,-1)]
    d="M"+" L".join(f"{ch.X(x):.1f},{ch.Y(y):.1f}" for x,y in pts)+"Z"
    ch.p.append(f'<path d="{d}" fill="{pal(k)}" opacity=".6"/>'); base=top_
cd={d:cost_d[d] for d in alld}
secs.append(sect("API-equivalent cost per week, by model","Stacked: where the spend went. Weeks start Monday.",
  ch.svg()+legend([(k,m) for k,(m,_) in enumerate(stack)]),
  f"Latest week ${tot[-1]:,.0f}; the week before ${tot[-2]:,.0f}; last 7 days ${sum(cd[d] for d in alld[-7:]):,.0f} (measured; API-priced, not what the plan charges)."))
css='''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Life dashboard prototype</title><style>
:root{--bg:#fff;--fg:#1c1c1e;--mut:#6b6b70;--card:#f5f5f7;--g:#e4e6eb;--c0:#3b6fb6;--c1:#d9822b;--c2:#d1453b;--c3:#2f9e8f;--c4:#7a5bb5;--c5:#3a9a4f;--c6:#555}
@media(prefers-color-scheme:dark){:root{--bg:#141416;--fg:#ececef;--mut:#9a9aa2;--card:#1d1d21;--g:#2c2e35;--c0:#6fa3ec;--c1:#f0a255;--c2:#ef6b5f;--c3:#55c7b6;--c4:#a98bea;--c5:#5ccf75;--c6:#b5b5bd}}
body{background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;margin:0 auto;max-width:960px;padding:14px 16px 60px}
h1{font-size:20px;margin:0 0 2px}h2{font-size:16px;margin:0}section{background:var(--card);border-radius:12px;padding:12px 14px;margin:14px 0}
.sub{color:var(--mut);margin:2px 0 8px;font-size:13px}.note{margin:6px 0 0;font-size:13px}.band{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);margin:26px 0 -6px}
svg.ch{width:100%;height:auto;display:block}.t{font-size:10px;fill:var(--mut)}.g{stroke:var(--g);stroke-width:1}.g2{stroke:var(--g);stroke-width:1;opacity:.5}.mid{stroke:var(--mut);stroke-dasharray:4 3;stroke-width:1}
.lg{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--mut);margin:4px 0}.lg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
</style>'''
head=f'<h1>Life first, then Claude</h1><p class=sub>Prototype on your real metrics.db, {D0:%b %-d} to {D1:%b %-d}. Local time ({TZ}).</p>'
body=head+'<div class=band>Your days</div>'+"".join(secs[:3])+'<div class=band>Right now</div>'+secs[3]+'<div class=band>Claude: friction, decisions, cost</div>'+"".join(secs[4:])
open(OUT,"w").write(css+body); print(OUT, len(alld),"days")
