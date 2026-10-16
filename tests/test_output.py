import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import hashlib
import pytest
from portfolio_allocation.__main__ import run
from .conftest import ROOT


@pytest.fixture(scope='module')
def generated_dashboard(tmp_path_factory):
    output_root=tmp_path_factory.mktemp('dashboard')/'output'
    source=ROOT/'files/ib_U5157275_audit.xlsx'
    p,r,n,report,manifest=run(source,output_root,ROOT/'fx_cache',
                            offline=True,spinoff_policy='broker-pl')
    output=output_root/source.stem
    return output,p,r,manifest


def test_complete_cli_exports_readonly_input_and_dashboard(generated_dashboard):
    output,p,r,manifest=generated_dashboard
    assert manifest['invalid_states']==0
    assert not any(path.is_file() for path in output.parent.iterdir())
    for name in ['allocation_dashboard.html','allocation_timeseries.csv','reconciliation_report.csv']:
        assert (output/name).stat().st_size>100
    with open(output/'allocation_timeseries.csv',encoding='utf-8-sig',newline='') as handle:
        rows=list(csv.DictReader(handle))
    assert len(rows)==len(p.states)*(len(r.items)+1)
    assert float(next(row for row in rows if row['instrument_key']=='Cash')['weight_percent'])==100
    assert 'inferred' in {row['basis_status'] for row in rows}
    if shutil.which('node'):
        result=subprocess.run(['node',str(ROOT/'tools/verify_dashboard.cjs'),str(output/'allocation_dashboard.html')],
                              capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
    with open(output/'realized_profit_timeseries.csv',encoding='utf-8-sig',newline='') as handle:
        profit_rows=list(csv.DictReader(handle))
    assert len(profit_rows)==len(p.states)*3  # USD, RUB, EUR display views.
    usd_rows=[row for row in profit_rows if row['display_currency']=='USD']
    assert float(usd_rows[0]['cumulative_realized'])==0
    assert float(usd_rows[-1]['cumulative_realized'])==manifest['realized_profit_usd']
    assert 'native_cumulative' in usd_rows[-1] and 'fx_used' in usd_rows[-1]
    assert (output/'realized_profit_events.csv').stat().st_size>100


@pytest.mark.skipif(not shutil.which('node') or not (ROOT/'.qa/node_modules/jsdom').exists(),
                    reason='Optional real-Plotly test requires Node and npm ci --prefix .qa')
def test_real_plotly_renders_asset_class_mode_and_back(generated_dashboard):
    output,_,_,_=generated_dashboard
    result=subprocess.run(['node',str(ROOT/'tools/verify_plotly_render.cjs'),str(output/'allocation_dashboard.html')],
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_cli_separates_workbooks_and_prints_actual_dashboard_path(generated_dashboard,tmp_path):
    first_output,_,_,_=generated_dashboard
    first_html=first_output/'allocation_dashboard.html'
    original_hash=hashlib.sha256(first_html.read_bytes()).hexdigest()
    # Same valid workbook under a distinct filename, including spaces and dots.
    renamed=tmp_path/'Another audit.v2.xlsx'
    shutil.copyfile(ROOT/'files/ib_U5157275_audit.xlsx',renamed)
    result=subprocess.run([sys.executable,'-m','portfolio_allocation','--input',str(renamed),
                           '--output-dir',str(first_output.parent),'--fx-cache',str(ROOT/'fx_cache'),
                           '--offline','--spinoff-policy','broker-pl'],cwd=ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    destination=first_output.parent/renamed.stem
    expected={'allocation_dashboard.html','allocation_timeseries.csv','reconciliation_report.csv',
              'cash_ledger.csv','fx_usage.csv','normalized_events.json','run_manifest.json',
              'realized_profit_timeseries.csv','realized_profit_events.csv','currency_settlements.csv',
              'profit_operation_audit.csv','profit_source_coverage.csv','profit_fifo_comparison.csv'}
    assert {p.name for p in destination.iterdir()}==expected
    assert f'Dashboard: {destination/"allocation_dashboard.html"}' in result.stdout
    assert hashlib.sha256(first_html.read_bytes()).hexdigest()==original_hash
    assert not any(path.is_file() for path in first_output.parent.iterdir())
