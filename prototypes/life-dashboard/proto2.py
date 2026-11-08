import json,sys,collections,math
src=open("/home/solace/claude/.claude/worktrees/pr-424-fixup-dashboard-demo-278257/.scratch/proto.py").read().split("# 1 day shape")[0]
sys.argv=[sys.argv[0],"/dev/null"]+sys.argv[1:]; OUT2=sys.argv[2]
exec(src)
T,B=10,4
_full=open("/home/solace/claude/.claude/worktrees/pr-424-fixup-dashboard-demo-278257/.scratch/proto.py").read()
css=_full[_full.index("css='''")+6:_full.index("</style>'''")+8]
_pr=json.load(open("/home/solace/claude/.claude/worktrees/pr-424-fixup-dashboard-demo-278257/.scratch/prompts.json"))
prompts=[iso(t).timestamp() for t,f in _pr if not f]; pasted=[iso(t).timestamp() for t,f in _pr if f]
end=max(r[0] for r in rows)+60
# sessions as intervals; cost spread evenly over each session (an assumption)
iv=[]
for s in S:
    try: a=iso(s["started_at"] or s["ts"]).timestamp(); b=iso(s["ended_at"]).timestamp() if s.get("ended_at") else a+60
    except Exception: continue
    iv.append((a,max(b,a+60),s["cost_usd"] or 0))
fts=[iso(r[0]).timestamp() for r in c.execute("select ts from friction where retracted=0").fetchall()]
dts=[iso(r[0]).timestamp() for r in c.execute("select ts from decisions").fetchall()]
# streaks: minutes since the last gap over 5 min; gaps for shading
am=[r[0]//60 for r in act]; streak={}; run=0; prev=None; gaps=[]
for m in am:
    run=run+1 if prev is not None and m-prev<=5 else 1
    if prev is not None and m-prev>5: gaps.append((prev*60+60,m*60))
    streak[m]=run; prev=m
import bisect
RES=sorted(m*60 for m,v in streak.items() if v==1); fts.sort(); dts.sort()
def saw(ev,start,bk,nb):
    out=[]
    for i in range(nb):
        te=start+(i+1)*bk; k=bisect.bisect_right(RES,te)-1; lr=RES[k] if k>=0 else 0
        out.append(bisect.bisect_right(ev,te)-bisect.bisect_left(ev,lr))
    return out
LANES=[("Keystrokes","k"),("Clicks · scroll","c"),("Prompts typed","p"),("Sessions","s"),("API-equiv $","$"),("Decisions · friction","d"),("Unbroken stretch (min)","w")]
RANGES=[("1 day",86400,300,"5 min"),("3 days",3*86400,900,"15 min"),("7 days",7*86400,3600,"1 hour"),("30 days",30*86400,7200,"2 hours")]
LH=96
def build(span,bk,label):
    start=end-span; nb=span//bk; x=lambda t:(t-start)/bk
    inb=lambda t:0<=int((t-start)//bk)<nb
    K=[0]*nb;C=[0]*nb;Sc=[0]*nb;P=[0]*nb;O=[0]*nb;A=[0]*nb;CO=[0.0]*nb;DE=[0]*nb;FR=[0]*nb;WK=[0]*nb
    for t,k,cl,sc,mv,afk in act:
        if start<=t<end: b=int((t-start)//bk); K[b]+=k; C[b]+=cl; Sc[b]+=sc
    for m,v in streak.items():
        t=m*60
        if start<=t<end: b=int((t-start)//bk); WK[b]=max(WK[b],v)
    PP=[0]*nb
    for t in prompts:
        if inb(t): P[int((t-start)//bk)]+=1
    for t in pasted:
        if inb(t): PP[int((t-start)//bk)]+=1
    for t in fts:
        if inb(t): FR[int((t-start)//bk)]+=1
    for t in dts:
        if inb(t): DE[int((t-start)//bk)]+=1
    for a,b2,usd in iv:
        if inb(a): O[int((a-start)//bk)]+=1
        lo=max(a,start); hi=min(b2,end)
        if hi<=lo: continue
        for b in range(int((lo-start)//bk),min(nb,int((hi-start)//bk)+1)):
            bs=start+b*bk; ov=min(hi,bs+bk)-max(lo,bs)
            if ov>0: A[b]+=1; CO[b]+=usd*ov/(b2-a)
    lanes=[]
    def lane(name,series,kind="bars"):
        lanes.append((name,series))
    HS=[LH+34,LH+34,LH,LH+10]; YS=[sum(HS[:i]) for i in range(len(HS))]; Ht=sum(HS)+22
    out=[f'<svg viewBox="0 0 {W} {Ht}" class="ch">']
    step={86400:3*3600,3*86400:12*3600,7*86400:86400,30*86400:5*86400}[span]
    t=math.ceil(start/step)*step; ticks=[]
    while t<end:
        d=loc(t); ticks.append((x(t),d.strftime("%a %-d %H:%M") if step<86400 else d.strftime("%b %-d"))); t+=step
    def lane_svg(i,name,fn,ymax,fmt,ymax2=None,fmt2=None):
        h=HS[i]; ch=Ch(0,nb,0,ymax*1.1 or 1,h=h); ch2=Ch(0,nb,0,(ymax2 or 1)*1.1,h=h)
        for xt,_ in ticks: ch.p.append(f'<line x1="{ch.X(xt):.1f}" x2="{ch.X(xt):.1f}" y1="{T}" y2="{h-B}" class="g2"/>')
        for a,b2 in gaps:
            if b2-a>=(180*60 if span>=7*86400 else 600) and b2>start and a<end:
                xa=ch.X(max(0,x(a))); xb=ch.X(min(nb,x(b2)))
                ch.p.append(f'<rect x="{xa:.1f}" y="{T}" width="{max(1,xb-xa):.1f}" height="{h-T-B}" class="{"sl" if (b2-a)>=3*3600 else "br"}"/>')
        ch.grid([0,ymax],fmt)
        if ymax2:
            for v in (0,ymax2): ch.p.append(f'<text x="{W-R+2}" y="{ch2.Y(v)+3:.1f}" class="t2">{fmt2(v)}</text>')
        fn(ch,ch2)
        out.append(f'<g transform="translate(0,{YS[i]})"><text x="{L}" y="9" class="ln">{name}</text>{"".join(ch.p)}{"".join(ch2.p)}</g>')
    ctr=lambda arr:[(i+.5,v) for i,v in enumerate(arr)]
    bw=max(1.5,(W-L-R)/nb*.8)
    PT=[x+y for x,y in zip(P,PP)]
    ak=[v for v in K if v>0]; ap=[v for v in PT if v>0]
    avgk=sum(ak)/len(ak) if ak else 1; avgp=sum(ap)/len(ap) if ap else 1; ratio=avgk/avgp
    kmax=max(K) or 1
    pmax=max(kmax/ratio,max(PT) or 1)           # right axis: same height as the left, scaled so typical prompts sit where typical keys do
    def inp(ch,ch2):
        ch.p.append(f'<line x1="{L}" x2="{W-R}" y1="{ch.Y(avgk):.1f}" y2="{ch.Y(avgk):.1f}" stroke="{pal(0)}" stroke-dasharray="2 4" opacity=".5"/>'
                    f'<text x="{L+4}" y="{ch.Y(avgk)-3:.1f}" class="t">average keys per active bucket: {avgk:,.0f}</text>')
        ch.line(ctr(K),0,1.6); ch2.line(ctr(PT),4,2)
    lane_svg(1,f"Input: keystrokes (blue, left) · prompts typed (violet, right). Scaled so 1 prompt ≈ {ratio:,.0f} keys",
             inp,kmax,lambda v:f"{v:,.0f}",pmax,lambda v:f"{v:.1f}".rstrip("0").rstrip("."))
    m=max(max(C),max(Sc)) or 1
    lane_svg(2,"Clicks (orange) · scroll (teal)",lambda ch,ch2:(ch.line(ctr(C),1,1.5),ch.line(ctr(Sc),3,1.5)),m,lambda v:f"{v:,.0f}")
    DS=saw(dts,start,bk,nb); FS=saw(fts,start,bk,nb)
    m=max(max(DS),max(FS),max(DE),max(FR)) or 1; wm=max(WK) or 1
    def df(ch,ch2):
        pts=[(i+.5,v) for i,v in enumerate(WK)]
        d="M"+" L".join(f"{ch2.X(xx):.1f},{ch2.Y(y):.1f}" for xx,y in [(0,0)]+pts+[(nb,0)])+"Z"
        ch.p.insert(0,f'<path d="{d}" fill="{pal(1)}" opacity=".16"/>')
        ch.line(ctr(DE),6,1,op=.35); ch.line(ctr(FR),2,1,op=.35); ch.line(ctr(DS),6,1.9); ch.line(ctr(FS),2,2.1)
    lane_svg(0,"Decisions (grey) · friction (red): bold = running count since your last break (resets with it), thin = count in the bucket · orange fill: minutes since last break",df,m,lambda v:f"{v:g}",wm,lambda v:f"{v:g}m")
    def ses(ch,ch2): ch2.bars(ctr(CO),5,bw,.55); ch.line(ctr(A),1,1.8)
    lane_svg(3,"Sessions running (line, left axis) · API-equivalent $ (green bars, right axis, spread over each session's run)",
             ses,max(A) or 1,lambda v:f"{v:g}",max(CO) or 1,lambda v:f"${v:,.0f}")
    ch0=Ch(0,nb,0,1,h=LH)
    for xt,lab in ticks: out.append(f'<text x="{ch0.X(xt):.1f}" y="{Ht-6}" class="t" text-anchor="middle">{lab}</text>')
    out.append('</svg>')
    return "".join(out)
radios="".join(f'<input type=radio name=r id=r{i} {"checked" if i==1 else ""}>' for i in range(len(RANGES)))
tabs="".join(f'<label for=r{i}>{n} <small>· {b}</small></label>' for i,(n,_,_,b) in enumerate(RANGES))
panels="".join(f'<div class=pn id=pn{i}>{build(s,b,n)}</div>' for i,(n,s,b,_) in enumerate(RANGES))
sel="".join(f'#r{i}:checked~.tabs label[for=r{i}]{{background:var(--c0);color:#fff}}#r{i}:checked~#pn{i}{{display:block}}' for i in range(len(RANGES)))
css=css.replace("</style>",f'''input[type=radio]{{position:absolute;opacity:0}}.tabs{{display:flex;gap:6px;margin:8px 0}}.tabs label{{padding:6px 12px;border-radius:99px;background:var(--card);cursor:pointer;font-size:13px}}small{{opacity:.7}}
.pn{{display:none}}{sel}.br{{fill:var(--c1);opacity:.14}}.sl{{fill:var(--c4);opacity:.22}}.t2{{font-size:10px;fill:var(--mut)}}.ln{{font-size:11px;fill:var(--fg);font-weight:600}}
</style>''')
body=f'<h1>One time axis, four lanes</h1><p class=sub>Pick a range; each range sets its own bucket size. Orange bands are breaks of 10 min or more (30 min or more on the 7 and 30 day views); violet bands are gaps of 3 hours or more, which is sleep or away. Local time. Newest data at the right edge.</p>{radios}<div class=tabs>{tabs}</div>{panels}<p class=note>Prompts come from the transcripts on this machine (my count is higher than metrics.db\'s 1,977 for 31 days, probably because it includes injected user messages; treat as an estimate). Cost is spread evenly across each session\'s run (an assumption). Sessions running counts a session in every bucket it overlaps.</p>'
open(OUT2,"w").write(css+body); print(OUT2)
