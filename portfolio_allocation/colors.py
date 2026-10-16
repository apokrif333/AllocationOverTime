"""Farthest-point CIELAB palette with persisted instrument assignments."""
import hashlib
import json
import math
from pathlib import Path

CASH_COLOR = '#929ca8'


def lab_rgb(l,a,b):
    fy=(l+16)/116
    xyz=[fy+a/500,fy,fy-b/200]
    xyz=[v**3 if v**3>216/24389 else (116*v-16)/903.3 for v in xyz]
    x,y,z=xyz[0]*.95047,xyz[1],xyz[2]*1.08883
    linear=[3.2404542*x-1.5371385*y-.4985314*z,
            -.969266*x+1.8760108*y+.041556*z,
            .0556434*x-.2040259*y+1.0572252*z]
    if any(v<0 or v>1 for v in linear):
        return None
    rgb=[12.92*v if v<=.0031308 else 1.055*v**(1/2.4)-.055 for v in linear]
    return '#'+''.join(f'{round(v*255):02x}' for v in rgb)


def palette(keys,cache_file=None):
    path=Path(cache_file) if cache_file else None
    saved=json.loads(path.read_text()) if path and path.exists() else {}
    saved['Cash']=CASH_COLOR
    saved['CLASS:Cash']=CASH_COLOR
    candidates=[]
    for l in (37,49,61,73,82):
        for chroma in (30,48,66):
            for hue in range(0,360,7):
                a,b=chroma*math.cos(math.radians(hue)),chroma*math.sin(math.radians(hue))
                rgb=lab_rgb(l,a,b)
                if rgb:
                    candidates.append(((l,a,b),rgb))
    # Recover coordinates of cached colors, retaining every existing assignment.
    reverse={rgb:lab for lab,rgb in candidates}
    chosen=[reverse[color] for color in saved.values() if color in reverse]
    used=set(saved.values())
    for key in sorted(keys):
        if key in saved:
            continue
        seed=int(hashlib.sha256(key.encode()).hexdigest()[:12],16)
        def score(candidate):
            lab,rgb=candidate
            distance=min((sum((x-y)**2 for x,y in zip(lab,old)) for old in chosen),default=1000)
            # Stable tie break changes the start hue without reducing separation.
            tie=int(hashlib.sha256((key+rgb).encode()).hexdigest()[:10],16)
            return distance,tie^seed
        available=[c for c in candidates if c[1] not in used]
        if not available:
            raise ValueError('Unique perceptual palette exhausted')
        lab,color=max(available,key=score)
        saved[key]=color
        chosen.append(lab)
        used.add(color)
    if path:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(saved,sort_keys=True,indent=2),encoding='utf-8')
    return {key:saved[key] for key in keys}
