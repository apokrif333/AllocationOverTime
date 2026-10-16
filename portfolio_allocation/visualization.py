"""Self-contained Plotly dashboard; weights are computed before any UI filtering."""
from dataclasses import asdict
import json
from pathlib import Path
from plotly.offline import get_plotlyjs
from .colors import palette
from .export import json_default


def filtered_values(state,keys):
    """View-only projection. Never recompute or normalize the denominator."""
    return {key:state.weights.get(key) for key in keys}


def build_dashboard(path,states,instruments,reconciliation,metadata,color_cache,profit=None):
    all_keys=sorted(instruments)+['Cash']
    classes=sorted({i.asset_class for i in instruments.values()}|{'Cash','Short-option collateral'})
    colors=palette(all_keys+['CLASS:'+c for c in classes],color_cache)
    payload=dict(states=[asdict(s) for s in states],instruments={k:asdict(i) for k,i in instruments.items()},
                 colors=colors,reconciliation=reconciliation,metadata=metadata,profit=profit)
    data=json.dumps(payload,default=json_default,ensure_ascii=False).replace('<','\\u003c')
    template=Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8')
    template=template.replace('__PROFIT_JS__',Path(__file__).with_name('profit_ui.js').read_text(encoding='utf-8'))
    path.write_text(template.replace('__PLOTLY_JS__',get_plotlyjs()).replace('__DATA_JSON__',data),encoding='utf-8')
