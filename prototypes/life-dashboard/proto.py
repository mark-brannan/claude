#!/usr/bin/env python3
"""Life-first dashboard, daily view: when days start and end, hours, keystrokes, friction, cost.
Usage: proto.py OUT.html   (reads metrics.db read-only; LIFE_DASHBOARD_DB overrides the path)"""
import sys, math, html, collections, datetime as dt
from common import *
OUT=sys.argv[1]
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
  f"Latest last-input in the past 7 days: {(f'{int(max(lastn)%24):02d}:{int(max(lastn)%1*60):02d}' if lastn else 'none')}. {late} of {len(last)} days since {D0:%b %-d} ran past midnight (measured)."))
# 2 hours & breaks
hmax=max(max(hh.values(),default=1),max(longest.values(),default=1))
ch=Ch(0,N-1,0,hmax*1.08); ch.grid([v for v in range(0,int(hmax)+1,2)],lambda v:f"{v:g}h"); ch.xt(dticks())
ch.bars([(i,hh.get(d)) for i,d in enumerate(alld)],0,8); ch.line([(i,longest.get(d)) for i,d in enumerate(alld)],3,2)
ch.line(trail(hh),1,2,"5 3")
secs.append(sect("Time at the keyboard, and the longest stretch without a break",f"Bars: hours with input. Orange: longest stretch with no gap over {BREAK} minutes. Dashed: 7-day average of hours.",
  ch.svg()+legend([(0,"hours with input"),(3,"longest unbroken stretch"),(1,"7-day average hours")]),
  f"7-day average {sum(v for _,v in trail(hh)[-1:])/1:.1f} h/day; longest unbroken stretch in the window {max(longest.values(),default=0):.1f} h (measured)."))
# 3 keystrokes/day
kmax=max(keys.values(),default=1)
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
        if start<=t<start+WIN: o[int((t-start)//BK)]+=1
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
fm=max(frh.values(),default=1)
ch=Ch(0,N-1,0,fm*1.08); ch.grid([round(fm*f/4,1) for f in range(5)],lambda v:f"{v:.1f}"); ch.xt(dticks())
ch.bars([(i,frh.get(d)) for i,d in enumerate(alld)],2,8,.35); ch.line(trail(frh),2,2.2)
dh={d:(dec_d[d]/hh[d]) for d in alld if d in hh and hh[d]>=1}
dm=max(dh.values(),default=1); ch2=Ch(0,N-1,0,dm*1.08); ch2.grid([round(dm*f/4,1) for f in range(5)],lambda v:f"{v:.1f}"); ch2.xt(dticks())
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
cd={d:cost_d[d] for d in alld}   # same session_cost source as the chart
secs.append(sect("API-equivalent cost per week, by model","Stacked: where the spend went. Weeks start Monday.",
  ch.svg()+legend([(k,m) for k,(m,_) in enumerate(stack)]),
  f"Latest week ${tot[-1]:,.0f}; the week before ${(tot[-2] if len(tot)>1 else 0):,.0f}; last 7 days ${sum(cd[d] for d in alld[-7:]):,.0f} (measured; API-priced, not what the plan charges)."))
head=f'<h1>Life first, then Claude</h1><p class=sub>Your real metrics.db, {D0:%b %-d} to {D1:%b %-d}. Local time ({TZ}).</p>'
body=head+'<div class=band>Your days</div>'+"".join(secs[:3])+'<div class=band>Right now</div>'+secs[3]+'<div class=band>Claude: friction, decisions, cost</div>'+"".join(secs[4:])
open(OUT,"w").write(CSS+body); print(OUT, len(alld),"days")
