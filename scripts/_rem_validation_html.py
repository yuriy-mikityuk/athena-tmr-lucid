#!/usr/bin/env python3
"""Render a self-contained HTML overlay for validate_rem_detection.py.

Two stacked panels share one time axis (no dual-axis):
  * p_rem over the night, with the gate enter-threshold and gate-open shading
  * YASA hypnogram staircase, REM epochs highlighted
plus an agreement strip (gate-open vs YASA-REM: hit / false-alarm / miss).
"""

from __future__ import annotations

import json
import math
from typing import Dict, List


def build_html(result: Dict[str, object]) -> str:
    epoch_seconds = float(result["epoch_seconds"])
    matched: List[Dict[str, object]] = result["matched"]  # type: ignore[assignment]
    points = [
        {
            "t": round(int(m["epoch"]) * epoch_seconds / 3600.0, 4),
            "p": round(float(m["p_rem"]), 4),
            "g": 1 if m["gate_open"] else 0,
            "s": str(m["ref_stage"]),
            "r": int(m["ref_rem"]),
        }
        for m in matched
    ]
    gate = result["gate_vs_ref"]
    tm = result["threshold_metrics"]
    enter_key = next((k for k in tm if k.startswith("enter_")), "at_0.5")
    auc = result["roc_auc"]
    tool = str(result.get("reference", {}).get("tool", "reference")).upper()

    def stat(x: object) -> str:
        return "n/a" if (isinstance(x, float) and not math.isfinite(x)) else (f"{x:.2f}" if isinstance(x, float) else str(x))

    stats = [
        ("Matched epochs", str(result["epochs_matched"])),
        (f"{tool} REM", f"{result['ref_rem_epochs']} ({result['ref_rem_fraction']*100:.0f}%)"),
        ("ROC-AUC", stat(auc)),
        ("Gate precision", stat(gate["precision"])),
        ("Gate recall", stat(gate["recall"])),
        ("Gate open", f"{gate['gate_open_minutes']} min"),
    ]
    stat_tiles = "".join(
        f'<div class="tile"><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in stats
    )

    enter_thr = 0.70
    try:
        enter_thr = float(enter_key.split("_", 1)[1])
    except (ValueError, IndexError):
        pass

    return _TEMPLATE.format(
        recording=result["recording"],
        eeg=result["reference"]["eeg"],
        eog=result["reference"].get("eog"),
        tool=tool,
        caveat=_CAVEATS.get(tool.lower(), _CAVEATS["yasa"]),
        stat_tiles=stat_tiles,
        data_json=json.dumps(points, separators=(",", ":")),
        enter_thr=enter_thr,
    )


# Reference-specific caveat (HTML). YASA mis-fits the Muse montage; GSSC fits it
# far better but is still an automated proxy.
_CAVEATS = {
    "yasa": (
        "<strong>Read as directional, not a grade.</strong> YASA is an automated proxy trained on "
        "central (C3/C4) PSG montages; the Muse provides only frontal/temporal channels referenced near "
        "Fpz and no EMG, so the reference itself mis-scores many W/N1/REM epochs. This measures agreement "
        "between two imperfect estimators on one night, not accuracy against sleep-lab truth."
    ),
    "gssc": (
        "<strong>Read as directional, not truth.</strong> GSSC is a neural stager whose training set "
        "includes frontal derivations and which stages from a single channel, so it fits the Muse montage "
        "far better than YASA &mdash; but it is still an automated proxy, not PSG. Validate against a few "
        "manually-scored nights before treating its REM calls as ground truth."
    ),
}


_TEMPLATE = """<title>REM validation - {recording}</title>
<style>
.vr {{
  --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --base:#c3c2b7; --p:#2a78d6; --pfill:rgba(42,120,214,0.16);
  --rem:#4a3aa7; --hit:#0ca30c; --fa:#fab219; --miss:#d03b3b; --border:rgba(11,11,11,0.10);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif; background:var(--page); color:var(--ink);
}}
@media (prefers-color-scheme:dark){{ .vr{{ --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7;
  --muted:#898781; --grid:#2c2c2a; --base:#383835; --p:#3987e5; --pfill:rgba(57,135,229,0.20);
  --rem:#9085e9; --border:rgba(255,255,255,0.10); }} }}
:root[data-theme="dark"] .vr{{ --surface:#1a1a19; --page:#0d0d0d; --ink:#fff; --ink2:#c3c2b7; --grid:#2c2c2a;
  --base:#383835; --p:#3987e5; --pfill:rgba(57,135,229,0.20); --rem:#9085e9; --border:rgba(255,255,255,0.10); }}
:root[data-theme="light"] .vr{{ --surface:#fcfcfb; --page:#f9f9f7; --ink:#0b0b0b; --ink2:#52514e; --grid:#e1e0d9;
  --base:#c3c2b7; --p:#2a78d6; --pfill:rgba(42,120,214,0.16); --rem:#4a3aa7; --border:rgba(11,11,11,0.10); }}
*{{box-sizing:border-box}} body{{margin:0}}
.vr{{min-height:100vh; padding:28px 18px 50px}} .wrap{{max-width:940px; margin:0 auto}}
h1{{font-size:19px; margin:0 0 3px}} .sub{{color:var(--ink2); font-size:13px; margin:0 0 18px}}
.tiles{{display:flex; gap:10px; flex-wrap:wrap; margin-bottom:18px}}
.tile{{background:var(--surface); border:1px solid var(--border); border-radius:10px; padding:10px 14px; min-width:110px; flex:1}}
.tile .k{{font-size:11px; color:var(--muted); margin-bottom:3px}}
.tile .v{{font-size:19px; font-weight:600; font-variant-numeric:tabular-nums}}
.card{{background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:16px 16px 6px; margin-bottom:16px}}
.card h2{{font-size:13px; margin:0 0 10px; font-weight:600}}
svg{{display:block; width:100%; height:auto; overflow:visible}}
.grid{{stroke:var(--grid); stroke-width:1}} .base{{stroke:var(--base); stroke-width:1}}
.axis{{fill:var(--muted); font-size:10px; font-variant-numeric:tabular-nums}}
.pline{{fill:none; stroke:var(--p); stroke-width:1.6}} .pfill{{fill:var(--pfill)}}
.thr{{stroke:var(--base); stroke-width:1; stroke-dasharray:4 3}}
.gate{{fill:var(--hit); opacity:0.16}} .remstep{{fill:none; stroke:var(--rem); stroke-width:1.6}}
.legend{{display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--ink2); margin:2px 2px 12px}}
.legend span{{display:inline-flex; align-items:center; gap:5px}}
.sw{{width:11px; height:11px; border-radius:2px; display:inline-block}}
.caveat{{font-size:12px; color:var(--ink2); background:var(--surface); border:1px solid var(--border);
  border-radius:10px; padding:12px 14px; line-height:1.5}}
</style>
<div class="vr"><div class="wrap">
<h1>REM detection vs {tool} reference &mdash; {recording}</h1>
<p class="sub">Heuristic p_rem &amp; live gate vs {tool} auto-staging (eeg {eeg}, eog {eog}) &middot; proxy reference, not PSG</p>
<div class="tiles">{stat_tiles}</div>
<div class="legend">
  <span><i class="sw" style="background:var(--p)"></i>heuristic p_rem</span>
  <span><i class="sw" style="background:var(--hit)"></i>gate open</span>
  <span><i class="sw" style="background:var(--rem)"></i>{tool} REM</span>
  <span><i class="sw" style="background:var(--hit)"></i>hit</span>
  <span><i class="sw" style="background:var(--fa)"></i>false alarm</span>
  <span><i class="sw" style="background:var(--miss)"></i>miss</span>
</div>
<div class="card"><h2>p_rem over the night (dashed = gate enter {enter_thr:g}; green = gate open)</h2>
  <svg id="prem" viewBox="0 0 900 170" preserveAspectRatio="none"></svg></div>
<div class="card"><h2>{tool} hypnogram &amp; agreement strip</h2>
  <svg id="hyp" viewBox="0 0 900 170" preserveAspectRatio="none"></svg></div>
<div class="caveat">{caveat}</div>
</div></div>
<script>
const DATA={data_json}, ENTER={enter_thr};
const W=900,padL=32,padR=8;
const T=DATA.length?DATA[DATA.length-1].t:1;
function xs(t){{return padL+(t/(T||1))*(W-padL-padR);}}
const NS="http://www.w3.org/2000/svg";
function el(p,tag,at){{const n=document.createElementNS(NS,tag);for(const k in at)n.setAttribute(k,at[k]);p.appendChild(n);return n;}}
function xaxis(svg,H){{for(let h=0;h<=T+1e-6;h++){{const x=xs(h);el(svg,'text',{{x:x,y:H-3,'text-anchor':h<0.1?'start':(h>T-0.1?'end':'middle'),class:'axis'}}).textContent=h+'h';}}}}

// Panel 1: p_rem
(function(){{const svg=document.getElementById('prem'),H=170,top=8,bot=150,h=bot-top;
 const y=p=>bot-p*h;
 [0,0.5,1].forEach(v=>{{el(svg,'line',{{x1:padL,x2:W-padR,y1:y(v),y2:y(v),class:'grid'}});
   el(svg,'text',{{x:padL-5,y:y(v)+3,'text-anchor':'end',class:'axis'}}).textContent=v.toFixed(1);}});
 // gate-open shading
 const dt=DATA.length>1?(DATA[1].t-DATA[0].t):0.008;
 DATA.forEach(d=>{{if(d.g)el(svg,'rect',{{x:xs(d.t),y:top,width:Math.max(0.6,xs(d.t+dt)-xs(d.t)),height:h,class:'gate'}});}});
 // area + line
 let area='M '+xs(DATA[0].t)+' '+y(0),line='M '+xs(DATA[0].t)+' '+y(DATA[0].p);
 DATA.forEach((d,i)=>{{area+=' L '+xs(d.t)+' '+y(d.p);if(i>0)line+=' L '+xs(d.t)+' '+y(d.p);}});
 area+=' L '+xs(DATA[DATA.length-1].t)+' '+y(0)+' Z';
 el(svg,'path',{{d:area,class:'pfill'}});el(svg,'path',{{d:line,class:'pline'}});
 el(svg,'line',{{x1:padL,x2:W-padR,y1:y(ENTER),y2:y(ENTER),class:'thr'}});
 xaxis(svg,H);}})();

// Panel 2: hypnogram + agreement
(function(){{const svg=document.getElementById('hyp'),H=170,top=8,bot=120;
 const Lv={{'WAKE':4,'REM':3,'N1':2,'N2':1,'N3':0}},h=(bot-top)/4,y=s=>top+(4-(Lv[s]??2))*h;
 Object.keys(Lv).forEach(s=>{{el(svg,'line',{{x1:padL,x2:W-padR,y1:y(s),y2:y(s),class:'grid'}});
   el(svg,'text',{{x:padL-5,y:y(s)+3,'text-anchor':'end',class:'axis'}}).textContent=s;}});
 let d='M '+xs(DATA[0].t)+' '+y(DATA[0].s);
 for(let i=1;i<DATA.length;i++){{d+=' L '+xs(DATA[i].t)+' '+y(DATA[i-1].s)+' L '+xs(DATA[i].t)+' '+y(DATA[i].s);}}
 el(svg,'path',{{d:d,class:'remstep'}});
 // agreement strip
 const sy=bot+12,sh=16,dt=DATA.length>1?(DATA[1].t-DATA[0].t):0.008;
 DATA.forEach(d=>{{let c=null;if(d.g&&d.r)c='var(--hit)';else if(d.g&&!d.r)c='var(--fa)';else if(!d.g&&d.r)c='var(--miss)';
   if(c)el(svg,'rect',{{x:xs(d.t),y:sy,width:Math.max(0.6,xs(d.t+dt)-xs(d.t)),height:sh,fill:c}});}});
 el(svg,'text',{{x:padL-5,y:sy+11,'text-anchor':'end',class:'axis'}}).textContent='gate';
 xaxis(svg,H);}})();
</script>
"""
