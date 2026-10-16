import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from .allocation import Portfolio
from .events import Normalizer
from .export import TIMESERIES_COLUMNS, timeseries_rows, profit_timeseries_rows, write_csv, write_json
from .fx import FX
from .reconciliation import reconcile
from .visualization import build_dashboard
from .workbook import Workbook, Instruments
from .profit import RealizedProfit
from .profit_audit import source_coverage,fifo_comparison
from .workbook import timestamp

METHODOLOGY = ('Historical USD acquisition costs plus purchase fees, reduced by FIFO original costs; '
    'native cash translated at each event. Sales use gross proceeds less fees. Cash begins at zero. '
    'Short put collateral reserves available aggregate cash without creating cash; this is an estimate, not broker margin. '
    'Date-only transfers 00:00, corporate conversions 20:25, income 23:59, snapshots 23:59:59; exact trade times retained. '
    'Events at a timestamp are applied in source-priority/row order then shown as one state. '
    'Positive gross capital is used when aggregate cash is negative, and borrowing is shown separately. '
    'Unknown basis or unavailable FX makes weights unavailable. The full portfolio denominator never changes with UI filtering.')


def result_directory(input_path,output_root):
    """Keep each workbook's deliverables in its own directory under the root."""
    return Path(output_root).resolve()/Path(input_path).stem


def run(input_path,output_dir,cache_dir='fx_cache',offline=False,spinoff_policy='unknown',
        collateral_policy='cash-secured-puts',fx_commission_currency='USD',fx_archive=False,
        short_premium_policy='closed',profit_currency=None):
    wb=Workbook(input_path)
    output=result_directory(wb.path,output_dir)
    if output==wb.path or wb.path.parent==output and wb.path.name in {
        'allocation_dashboard.html','allocation_timeseries.csv','reconciliation_report.csv'}:
        raise ValueError('Output must not overwrite the input workbook')
    output.mkdir(parents=True,exist_ok=True)
    registry=Instruments(wb)
    normal=Normalizer(wb,registry,spinoff_policy,fx_commission_currency)
    fx=FX(cache_dir)
    currencies={e.currency for e in normal.events if e.currency}
    currencies.update(c for e in normal.events if e.kind=='forex' for c in (e.data['base'],e.data['quote']))
    if profit_currency:
        currencies.add(profit_currency)
    fx_dates={e.timestamp.date() for e in normal.events}
    fx_dates.update(timestamp(lot['acquired']).date() for e in normal.events
                    for lot in e.data.get('basis_lots',[]) if lot.get('acquired'))
    failures=fx.ensure(currencies,normal.events[0].timestamp.date(),wb.end_date,offline,fx_dates)
    if fx_archive and not offline and 'RUB' in currencies:
        failures.extend(fx.download_cbr_archive({day for day in fx_dates if day.isoformat()>'2022-03-01'}))
    profit=RealizedProfit(fx,wb['Fifo'],short_premium_policy,profit_currency)
    portfolio=Portfolio(registry.items,fx,collateral_policy,profit)
    states=portfolio.run(normal.events)
    coverage=source_coverage(wb,normal)
    fifo_checks=fifo_comparison(wb,normal,profit)
    report=reconcile(wb,portfolio,registry,normal)
    for name,rows in (('operation_audit',profit.audit.rows),('source_coverage',coverage),('fifo_comparison',fifo_checks)):
        errors=[row for row in rows if row['status']=='error']
        if errors:
            report.append(dict(category='profit:'+name,severity='blocking',
                sources='; '.join(str(row.get('sources') or row.get('source')) for row in errors),
                possible_cause=f'{len(errors)} unexplained profit audit failures; see profit_{name}.csv.'))
    for issue in profit.issues:
        report.append(dict(category='profit:'+issue.code,severity=issue.severity,date=issue.timestamp,
            instrument_key=issue.instrument,sources='; '.join(issue.sources),possible_cause=issue.details))
    if profit.unknown_count:
        report.append(dict(category='profit:incomplete_total',severity='blocking',sources='realized_profit_events.csv',
            possible_cause=f'{profit.unknown_count} realized components are unknown; cumulative total is unavailable. Known subtotal is labeled separately.'))
    for failure in failures:
        report.append(dict(category='fx_download',severity='warning',sources='fx_cache',possible_cause=failure))
    options=dict(spinoff_policy=spinoff_policy,collateral_policy=collateral_policy,
                 fx_commission_currency=fx_commission_currency,offline=offline,
                 short_premium_policy=short_premium_policy,profit_currency=profit.default_currency)
    transfer_status=Counter(e.data['basis_status'] for e in normal.events if e.kind=='security_in')
    basis_disclosure=(f'Incoming security lots: {transfer_status["documented"]} with documented original cost, '
                      f'{transfer_status["inferred"]} inferred, {transfer_status["unknown"]} unknown. ')
    if any(e.kind=='spinoff' for e in normal.events):
        basis_disclosure+='Spinoff costs are inferred only with corroborated evidence under broker-pl; otherwise unknown. '
    metadata=dict(input_name=wb.path.name,input_sha256=wb.sha256,
        fx_cache_sha256=hashlib.sha256(fx.cache_file.read_bytes()).hexdigest() if fx.cache_file.exists() else None,
        start=states[0].timestamp.isoformat(),end=states[-1].timestamp.isoformat(),
        state_count=len(states),event_count=len(normal.events),instrument_count=len(registry.items),
        valid_states=sum(s.valid for s in states),invalid_states=sum(not s.valid for s in states),
        severity_counts=dict(Counter(r['severity'] for r in report)),methodology=METHODOLOGY,
        realized_profit_usd=profit.states[-1]['cumulative_realized_usd'],
        realized_profit_native=profit.states[-1]['native_cumulative'],
        profit_currency=profit.default_currency,
        realized_profit_display=profit.states[-1]['by_currency'][profit.default_currency]['cumulative_realized'],
        profit_method='Native-currency FIFO profit; actual currency closures and debt repayments included. Whole cumulative balances translated on profit-event dates. No hypothetical USD cost for ordinary cash.',
        profit_audit_counts=dict(Counter(row['status'] for row in profit.audit.rows)),
        profit_source_counts=dict(Counter(row['status'] for row in coverage)),
        profit_fifo_counts=dict(Counter(row['status'] for row in fifo_checks)),
        profit_complete=profit.states[-1]['by_currency'][profit.default_currency]['complete'],
        run_options=json.dumps(options),
        basis_disclosure=basis_disclosure)
    write_csv(output/'allocation_timeseries.csv',timeseries_rows(states,registry.items),TIMESERIES_COLUMNS)
    write_csv(output/'reconciliation_report.csv',report)
    write_csv(output/'cash_ledger.csv',portfolio.cash.entries)
    write_csv(output/'fx_usage.csv',fx.usage.values())
    write_json(output/'normalized_events.json',portfolio.event_audit)
    write_json(output/'run_manifest.json',metadata)
    write_csv(output/'realized_profit_timeseries.csv',profit_timeseries_rows(profit.states))
    write_csv(output/'realized_profit_events.csv',[dict(e,native_cumulative=json.dumps(e['native_cumulative'],sort_keys=True)) for e in profit.entries])
    write_csv(output/'currency_settlements.csv',profit.currency_settlements.audit,
              ['timestamp','category','native_currency','quantity','profit_currency','historical_basis',
               'settlement_amount','realized_profit','basis_method','acquisition_date','acquisition_sources','settlement_sources'])
    write_csv(output/'profit_operation_audit.csv',profit.audit.rows)
    write_csv(output/'profit_source_coverage.csv',coverage)
    write_csv(output/'profit_fifo_comparison.csv',fifo_checks)
    profit_payload=dict(states=profit.states,issues=[asdict(i) for i in profit.issues],
                        short_premium_policy=short_premium_policy,currencies=profit.currencies,
                        default_currency=profit.default_currency)
    build_dashboard(output/'allocation_dashboard.html',states,registry.items,report,metadata,Path(cache_dir)/'instrument_colors.json',profit_payload)
    actual_hash=hashlib.sha256(wb.path.read_bytes()).hexdigest()
    if actual_hash!=wb.sha256:
        raise RuntimeError('Input workbook hash changed during execution')
    return portfolio,registry,normal,report,metadata


def main():
    parser=argparse.ArgumentParser(description='Historical FIFO-cost portfolio allocation from a read-only broker audit')
    parser.add_argument('--input',default='files/ib_U5157275_audit.xlsx',type=Path)
    parser.add_argument('--output-dir',default='output',type=Path,
                        help='Parent output directory; results go into <output-dir>/<input filename without extension>/')
    parser.add_argument('--fx-cache',default='fx_cache',type=Path)
    parser.add_argument('--offline',action='store_true',help='Use only cached observations; missing FX remains blocking')
    parser.add_argument('--fx-archive',action='store_true',help='Explicitly allow documented CBR archive mirror after direct source failures')
    parser.add_argument('--spinoff-policy',choices=['unknown','broker-pl'],default='unknown',help='Default: unknown basis. broker-pl: corroborated retrospective inference, clearly flagged')
    parser.add_argument('--collateral-policy',choices=['cash-secured-puts','none'],default='cash-secured-puts')
    parser.add_argument('--fx-commission-currency',choices=['USD','quote'],default='USD',help='Audit omits currency; USD inference matches both 2022 cash ledgers')
    parser.add_argument('--short-premium-policy',choices=['closed','cash'],default='closed',help='Realize net short-option premium at close/expiry (default), or explicitly at receipt')
    parser.add_argument('--profit-currency',help='Initial profit-chart display currency; default is the most frequent source currency. USD is always available in the chart.')
    parser.add_argument('--strict',action='store_true',help='Exit 2 after writing diagnostics when blocking or source error findings remain')
    args=parser.parse_args()
    _,_,_,report,meta=run(args.input,args.output_dir,args.fx_cache,args.offline,args.spinoff_policy,
                         args.collateral_policy,args.fx_commission_currency,args.fx_archive,
                         args.short_premium_policy,args.profit_currency)
    print(json.dumps({k:v for k,v in meta.items() if k not in ('methodology','basis_disclosure')},indent=2))
    print(f'Dashboard: {result_directory(args.input,args.output_dir)/"allocation_dashboard.html"}')
    if args.strict and any(r['severity'] in ('blocking','error') for r in report):
        raise SystemExit(2)


if __name__=='__main__':
    main()
