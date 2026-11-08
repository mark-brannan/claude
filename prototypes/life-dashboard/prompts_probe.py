import json,sqlite3,time,sys
t0=time.time()
c=sqlite3.connect("file:/home/solace/claude_prompts_scratch/state/global/metrics/dashboard/metrics.db?mode=ro",uri=True)
paths=[r[0] for r in c.execute("select path from typing where last_ts>datetime('now','-31 days')")]
out=[];nb=0
for p in paths:
    try: f=open(p,errors="replace")
    except OSError: continue
    for ln in f:
        if '"type":"user"' not in ln or '"tool_result"' in ln: continue
        try: o=json.loads(ln)
        except Exception: continue
        if o.get("type")!="user" or o.get("isSidechain") or o.get("isMeta"): continue
        m=o.get("message",{}).get("content")
        txt=m if isinstance(m,str) else "".join(b.get("text","") for b in m or [] if isinstance(b,dict))
        if not txt.strip() or txt.lstrip().startswith(("<system","<command","<local-command","Caveat")): continue
        out.append([o["timestamp"],1 if ("[Pasted text" in txt or "<pasted_content" in txt) else 0])
json.dump(out,open(sys.argv[1],"w"));print(len(out),len(paths),round(time.time()-t0,1),"s")
