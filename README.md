# Historical portfolio allocation

A local Python application that reconstructs IBKR, Tsifra and Halyk holdings with FIFO historical
USD acquisition costs and a separate signed cash ledger. It produces an offline,
self-contained Plotly HTML dashboard. No market prices are downloaded and the
source workbook is never modified.

Place the source workbook at `files/ib_U5157275_audit.xlsx` (or pass its own path
with `--input`). Private Excel inputs, generated reports under `output/`, local
inspection dumps and the detailed account profit audit are excluded from Git.
Integration tests require the corresponding local input workbooks; the public
central-bank FX cache is included for reproducibility. The inspection summary and
material accounting ambiguities are recorded in [SCHEMA_NOTES.md](SCHEMA_NOTES.md).

## Run

Python 3.11 or later:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m portfolio_allocation --input files\ib_U5157275_audit.xlsx --output-dir output --offline
```

The command above uses the supplied FX cache and the conservative default for
unknown spinoff basis. From April 2022 through the disposal of the affected
AT&T/WBD holdings, some allocation values are deliberately unavailable. Missing
amounts are blank in CSV, not zero.

The included `output/ib_U5157275_audit/` deliverables were generated with the explicitly selected
**provisional spinoff inference**:

```powershell
.venv\Scripts\python.exe -m portfolio_allocation --input files\ib_U5157275_audit.xlsx --output-dir output --offline --spinoff-policy broker-pl
```

This infers WBD basis of USD 537.71648796 from the later complete sale's net
proceeds minus the workbook's broker P/L. It is corroborated by the equal and
opposite AT&T broker-versus-canonical P/L difference (within one cent), allocated
out of the parent lots, and labeled **inferred**. It uses later information
retrospectively and is not an independently verified original basis allocation.
The default never performs this inference without the explicit option.

`--output-dir` specifies the parent directory. All result files are written to
`<output-dir>/<input filename without extension>/`; the workbook above therefore
produces `output/ib_U5157275_audit/`. Different input filenames get separate folders.

Open `output/ib_U5157275_audit/allocation_dashboard.html` directly in a browser. It contains Plotly,
data, styles and controller code; no web server, account connection, CDN or network
is required. The file contains the account's financial data, as do the CSVs.

To obtain FX for an uncached workbook or new dates, omit `--offline`. To explicitly
allow the documented CBR archive mirror when direct CBR access fails, also pass
`--fx-archive`. There is no rate-of-one fallback. Download failure is reported and
affected allocations remain unavailable. The cached bundle is sufficient for the
supplied workbook, so reproducible runs should use `--offline`.

Additional options:

* `--fx-cache PATH`: central-bank rates and persistent instrument colors.
* `--collateral-policy cash-secured-puts` (default) or `none`.
* `--profit-currency RUB` (or USD, KZT, another available currency): initial
  realized-profit display currency. The dashboard selector can change it later.
* `--fx-commission-currency USD` (default) or `quote`. The audit omits this field.
  USD treatment is an inference supported by both 2022 cash reconciliations;
  quote-currency treatment produces opposite USD 2 and RUB 2 differences.
* `--strict`: write all outputs, then exit 2 if blocking or original source error
  findings remain. Normal diagnostic generation exits 0 even with disclosed
  discrepancies. Exit 0 does not mean that the workbook is fully reconciled.

## Deliverables and audit trail

| File in `output/ib_U5157275_audit/` | Contents |
|---|---|
| `allocation_dashboard.html` | Interactive chart, liability history, selectors, date table, source events and reconciliation |
| `allocation_timeseries.csv` | Long-format rows for **every instrument and Cash at every state**, including zeros, invested USD, percentage, quantity, basis status, signed cash, collateral, borrowing, denominator, FX provenance and events |
| `reconciliation_report.csv` | Reconstructed versus reported cash and quantities, signed and absolute differences, relative differences, source rows and possible causes; original audit findings separately prefixed |
| `normalized_events.json` | Original trade IDs, source references, corporate evidence, inferred basis and FIFO removed basis |
| `cash_ledger.csv` | Every independently identified cash posting by currency, including both FX legs |
| `fx_usage.csv` | Requested date, rate actually used, observation date, source URL and staleness |
| `run_manifest.json` | Input SHA-256, run options, coverage and validity counts |
| `realized_profit_timeseries.csv` | One row per state and display currency: cumulative profit, native subtotals, categories, valuation date, FX provenance and unknown/inferred status |
| `realized_profit_events.csv` | Individual native-currency realized gains/losses and net receipts, with source rows and native running totals |
| `currency_settlements.csv` | Every actual currency/debt closure: settled units, opening basis, execution payment, native result and both source references |
| `profit_operation_audit.csv` | Every normalized event checked against native cash, remaining cost and deferred short premiums; capital movements excluded explicitly |
| `profit_source_coverage.csv` | Every Trades, Transfers, CorporateActions, Dividends, Coupons and Interest source row linked to its event |
| `profit_fifo_comparison.csv` | Independent native realized P/L comparison by execution ID against Fifo; documented spinoff offsets identified |

Security quantities are contracts, shares or bond face amounts as recorded, not
converted to market units. A short option's `invested_usd` is reserved collateral,
not premium received or the short's acquisition cost. A null value is unavailable.
`allocation_valid` means the allocation can be computed from the selected basis
policy and FX inputs. It does **not** certify agreement with broker cash.

CSV uses UTF-8 with BOM and full numeric precision. Percentages are in percentage
points. Relative discrepancies are absolute ratios (multiply by 100 for percent).
Relative difference is blank when the reported value is zero and the difference
is nonzero. Zero versus zero gives zero.

## Cumulative realized profit

The second main chart accumulates realized profit in each transaction's original
currency, starting at zero. Tsifra starts in RUB; the currency selector also
provides USD. Halyk provides USD and KZT. At each profit event, the **entire
accumulated native balance** is converted using that event date's rate. For mixed
currency accounts, each native subtotal is converted at the same valuation date
and the results are added. This is a presentation conversion, not another profit
transaction. For example, cumulative RUB 200 at RUB 100 per USD displays USD 2,
regardless of the exchange rates when the individual profits were received.

Cash deposits, purchases and account checkpoints without a profit posting do not
revalue this chart; it holds the preceding profit-event value. The date actually
used, published FX observation dates and native subtotals are exposed below it.
Hover points represent profit postings only; other account events do not create
profit tooltips. Boundary lines preserve the full account history without hover
points. Compact tooltips list distinct operation types for the calendar date;
individual operation details remain available below the chart.
The chart covers the complete portfolio and does not change with the security
selector, legend or allocation display mode. Date controls and chart clicks update
the category breakdown and individual realized events. Its CSV button exports
the selected currency. Capital allocation retains its historical USD basis rules.

Separately recorded `Transfers.Transfer_Type = tax` payments reduce cash and
realized profit; incoming tax refunds increase both. They appear under `Taxes`,
not external deposits/withdrawals. Income `Net_Amount` already includes its own
withholding and is not taxed again. A separate income commission is deducted
only when the gross/net fields establish that it is not already included.

## Tsifra audit

```powershell
.venv\Scripts\python.exe -m portfolio_allocation --input files\tsifra_1432280_audit.xlsx --output-dir output --offline --spinoff-policy broker-pl
```

Results go into `output/tsifra_1432280_audit/`. This file includes 22 separate
tax postings (21 payments and one refund), nine incoming security transfer lots,
and four small repo-interest commissions outside `Net_Amount`.

The corrected workbook provides original purchase dates and costs. GMKN and
SNGSP each arrive in two lots; transfer-to-FIFO matching uses ISIN and original
acquisition timestamp, and each FIFO fragment is consumed only once. FIFO disposals
follow original acquisition dates even if transfer rows arrive in another order.
All 274 allocation states are computable, including the initial transferred
positions. Transfers create no fictitious cash purchase.

Historical RUB observations have been added to the local cache; the same offline
command now works without rate gaps. Dates that fall on market closures retain
the actual preceding observation date and source. Online coverage checks include
intermediate event dates and transferred lots' purchase dates, not just the first
and last account dates. The original version with undated zero-cost placeholders
remains covered by a synthetic missing-data regression: those costs stay unknown.

Cash reconciliation discrepancies remain visible and are not balanced artificially.
Computable allocation and profit do not certify agreement with broker balances.
The `broker-pl` switch enables only corroborated spinoff inference.

## Halyk audit

```powershell
.venv\Scripts\python.exe -m portfolio_allocation --input files\halyk_1028197847_audit.xlsx --output-dir output --offline --spinoff-policy broker-pl
```

Halyk records redemptions as `Trades.Trade_Type = redemption` and repeats them
in `CorporateActions` as `maturity`. The matching instrument, date, currency,
signed quantity and gross proceeds identify a single event. The trade's commission
and cash proceeds are retained once, and the corporate record is evidence.
Generic redemptions without a supplementary corporate record are also supported.
The supplied file has ten such matched maturities, no security shorts, and 36
computable allocation states. Metadata identifies Treasury bills, inflation-linked
government bonds, corporate bonds and ETFs separately.

KZT/USD daily observations come from the official NBK dated RSS service:
https://nationalbank.kz/ru/page/rss. USD `description` is KZT per `quant` USD;
the normalized rate is `quant / description`. Original XML, requested/observation
dates, source URLs and SHA-256 hashes are cached. Online runs fetch missing KZT
observations; offline runs never download or use annual tax-reporting rates.
The supplied cache includes all 36 dates needed by this Halyk file.

This tax audit has no transfer/funding history (`Transfers` is empty), although
it supplies final cash snapshots. Replaying only trades and coupons from zero
produces USD -397,584.10886 and KZT -1,792,910.42, versus reported USD 1,087.91
and KZT 700.94. These are unreconciled funding shortfalls, not evidence of actual
broker borrowing. The dashboard labels them accordingly and exposes a blocking
`cash_funding_history_missing` finding. Deposits, withdrawals, conversions and/or
an explicit opening balance are needed for accurate cash allocation. No fabricated
funding is inserted. Computable security weights and identifiable native realized
profit do not certify complete cash or total account return.

## Realized-profit calculation

Included: net closing proceeds minus historical FIFO basis **in the security's
transaction currency** (including purchase commissions), losses as well as profits, maturities/calls, long-option
expiration losses, closed short-option net premiums, net dividends, signed bond
coupons/accrued-interest adjustments, net financing interest, explicit corporate
cash payouts, and identifiable fee refunds/standalone commissions. A RUB purchase
for 100 and sale for 120 contributes RUB 20 before applicable commissions,
regardless of either day's USD rate. Native income is accumulated in its own
currency before the whole cumulative balance is translated for display.

Excluded: deposits and withdrawals, incoming/outgoing securities, open-position
price changes, unrealized currency revaluations, exchange principal, and collateral
reservations/releases. Buying a security is not itself a realized loss. Its
purchase commission stays in basis until the corresponding lot closes. Closing
fees are deducted once. A spinoff/conversion carries basis and does not generate
income merely because new securities are delivered.

By default `--short-premium-policy closed` defers a short option's net premium
until its contracts close or expire. The GLD put contributes USD 309.8776472 on
2025-02-03; it contributes nothing to realized profit on its opening date.
`--short-premium-policy cash` is an explicit alternative cash-receipt convention:
it recognizes the net premium at receipt and later deducts closing payments,
without adding the premium a second time. Open long premiums remain excluded
until sale/expiry under both policies.

Ordinary RUB/KZT receipts and spending do not create hypothetical USD cash-lot
gains or losses. Positive cash is assigned an FX trading basis only if it was
actually purchased in a currency exchange; an actual later exchange closes that
basis in its settlement currency. Spending those units on securities, taxes or
other expenses does not create a virtual FX sale.

Negative native cash records borrowed units. An **actual FX purchase used to
repay that debt** realizes the difference between the settled debt's historical
basis and the actual execution payment. Borrowing caused by native purchases or
expenses uses the documented daily USD rate at borrowing; debt created by an
actual FX sale uses its actual receipt. Open debt is not marked to market in
profit. Native receipts that reduce debt do not create synthetic FX income.
Missing or incompatible settlement basis is explicitly unknown, never zero.

In IB on 2022-07-28, buying RUB 5,089,437.45349987 for USD 83,182.14987517 closes
debt with historical USD basis 64,380.91606976, recognizing **USD -18,801.23380541**
under `Currency borrowing`. This is separate from RUB debit interest already
expensed under `Interest`. Actual FX fees reduce profit once under fees, and the
exchange principal remains excluded. Details and opening/closing source rows are
exported to `currency_settlements.csv`. No balancing or hardcoded loss is inserted.

The seven source `Fifo` rows marked `fx_trade` are **not added** as income: they
provide no opening basis or verified realization, and their P/L values are
consistent with daily MTM. For example, the two EUR/USD opening executions imply
the same daily closing quote of 1.1541 from `Price + PnL / Quantity`, which is not
proof of realized profit. The [IBKR Trades reference](https://www.ibkrguides.com/reportingreference/reportguide/trades.htm)
distinguishes Forex MTM from realized P/L. Including these figures as well as
unverified currency gains would be incorrect. FX commissions are charged once
in the configured fee currency; exchange principal is never treated as income.

Treasury-bill and spinoff basis inferences carry into realized gains and remain
flagged. The unresolved cash-ledger differences can include omitted charges that
would also affect profit. The result is cumulative realized profit from the
identifiable supplied records under the selected policies, not a fully reconciled
broker-certified total. Unknown closing basis or an unlinked assignment/exercise
makes the full cumulative native total unavailable from that event on; a labeled
dotted line shows the known subtotal. Missing display FX affects only the relevant
currency view/date, not an otherwise known native profit. Rates are never replaced
with 1 or missing values with zero.

## Accounting and chronology

* Start native cash at zero. The first USD 100,000 deposit on 2021-11-22 is 100%
  Cash. Early RUB borrowing is retained in the native ledger.
* ISIN identifies securities. Options use description, expiration, strike, type,
  multiplier, underlying and asset category, resolving metadata by description
  as well as symbol. Different bond issues remain distinct.
* Purchase basis is `Amount + Commission` translated on acquisition date. Sales
  remove original FIFO USD basis and post `Amount - Commission` to cash. The
  audit's positive `Amount_With_Commission` on a sale is not net sale proceeds.
  Decimal arithmetic preserves fractional lots without fee duplication.
* Security transfers do not touch cash or create realized sales. In the current
  workbook, Treasury bill US912797FS14 enters on 2023-10-23 at documented USD
  **191,472.70 basis**, acquired on 2023-07-13, for face amount 200,000.
  Its 2024-06-12 redemption closes that lot and
  posts USD 200,000 once. No fictitious cash purchase is created.
* All 22 maturity/full-call duplicates are matched across Trades/CorporateActions
  by type, date, ISIN, signed quantity, currency and proceeds. Distinct Trade_IDs
  always survive, even for identical-looking executions. An exact repeated ID is
  suppressed; a conflicting repeated ID raises an error. Income/transfer records
  with no independent IDs are retained rather than arbitrarily collapsed.
* Explicit ERUS, AVGO and IPG conversion chains restore original historical ISINs
  that the derived Trades sheet had retrospectively remapped to successor IDs.
  Paired conversion quantities carry FIFO lots, acquisition dates and USD costs
  forward. Corporate `Value` is not cash. ERUS's separately recorded USD 61.7103
  corporate cash is posted once. All original source identifiers remain auditable.
* Dividends, coupons and interest post signed `Net_Amount`. Negative coupons are
  accrued-interest payments/adjustments. They affect cash, not bond basis. Taxes
  are not deducted again. No Interest commission values are populated in this
  workbook; net income is authoritative rather than guessed from gross values.
* FX transactions post signed base quantity and its opposite executed quote
  amount. Commissions are posted once in the disclosed configured fee currency.
  FX pairs are never investment traces. Cash then receives the valuation-date
  central-bank rate; historical security USD basis is not retranslated.
* Long options retain paid premium plus fees until FIFO disposal or expiration.
  Short premiums increase real cash and never become positive purchase basis.
  Cash-secured **equity/index short puts** reserve
  `abs(contracts) × strike × multiplier`, limited to available aggregate USD cash.
  Futures short options and calls are flagged uncovered without an invented
  margin model. The GLD put reserves USD 25,100 from 2025-01-16 to its closing
  trade on 2025-02-03. Its USD 324.9328972 net receipt and USD 15.05525 closing
  payment remain in cash after release. Short partial closes and expirations
  release collateral. Explicit assignment/exercise option-closing rows are
  supported when recorded separately from underlying delivery/payment; missing
  underlying evidence remains a warning, with no synthetic purchase invented.
* The chart denominator is positive security cost plus free positive cash and
  reserved collateral. Reservations are removed from free cash, not actual cash.
  If aggregate cash is negative, the positive gross-capital denominator excludes
  negative cash and borrowing is disclosed separately. Net cost capital is gross
  positive capital minus borrowing. None of these amounts is mark-to-market NAV.
* Full-portfolio percentages are calculated before filtering, never with Plotly
  `groupnorm`. A filtered subset or hidden legend traces can sum to less than
  100%. Every valid complete state is checked to 0.000001 percentage points.
* Events use workbook timestamps without assuming an unprovided timezone.
  Date-only transfers are 00:00, corporate actions 20:25 (the audit convention),
  income 23:59, and snapshot checkpoints 23:59:59. Within a timestamp, source
  priority and Excel row order provide deterministic sequencing. Simultaneous
  events emit one after-group state and retain all underlying records. Unknown
  intraday settlement order cannot be reconstructed from date-only records.
* The chart uses step-hold (`hv`) lines. Cash is retranslated only at recorded
  events and snapshot checkpoints. No daily transactions or market prices are
  invented. The chart ends at the final available account date, 2026-10-08.
  Positions' future 2026-12-31 labels are compared with that final state, explicitly
  flagged as forward labels, never treated as observed future account data.

## Historical FX and reproducibility

The cache holds raw downloaded responses, SHA-256 hashes, retrieval metadata and
normalized USD-per-native-unit rates. Existing raw files are reused. Delete or
move the relevant raw/cache files only when intentionally refreshing published
observations; keep them for reproducibility.

* [ECB reference rates and downloadable history](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html):
  EUR/USD and early RUB/USD via EUR. ECB suspended RUB publication after
  2022-03-01. This application does not carry that last fixing indefinitely.
* [Bank of Russia documented XML history](https://www.cbr.ru/development/sxml/):
  official RUB per USD (`R01235`), inverted to USD per RUB. Direct access failed
  during this build, which is why the alternate source is explicitly identified.
* [CBR daily archive documentation](https://www.cbr-xml-daily.ru/): republishes CBR
  fixings. Requested event dates are fetched from its archive and the response's
  observation date is recorded. Closed days fall back to a preceding publication.
  This is a third-party mirror, not a direct central-bank download.

Rates may never use a future observation. A preceding rate more than 14 calendar
days old is rejected. This is an explicit stale-data guard, not permission to
fabricate a rate. KZT tax-conversion fields are never used for USD valuation.
Additional currencies in ECB history are supported; unavailable ones block their
affected acquisition basis or cash valuation until documented rates are supplied.

## Dashboard controls

Use the search box to narrow the checkbox list, then select individual components
or choose **Only matches**. Switch between securities and asset classes. Highlight
an instrument to dim other traces. Click legend items, zoom or pan, use the date
range slider, or use the calendar/event slider for the full allocation table and
source events. Colors use a CIELAB farthest-point palette with persistent unique
security assignments in `fx_cache/instrument_colors.json`; Cash stays neutral in
both views. New instruments retain existing assignments. Dozens of traces can be
filtered rather than relying on color alone. CSV export always includes the full
portfolio, regardless of current filters.

Chart tooltips select the active filled band beneath the cursor at the preceding
event state. Closed positions with zero weight cannot capture a tooltip. The
compact tooltip shows the name, ISIN, calendar date, remaining invested USD and
percentage. Cash shows free cash; a short option shows estimated collateral.
Signed total cash, borrowing, the denominator and transaction details remain in
the accounting panels rather than repeating in each security tooltip. This hover
behavior requires Plotly 7.1 or later (included in `requirements.txt`).

Click any allocation-table column heading to sort, then click again to reverse
the direction. The active heading shows an arrow. Quantity, invested capital and
weight use their underlying numeric values; empty/unavailable values stay last.
The chosen order persists when changing dates, display modes or filters.

## Reconciliation findings and limitations

The 2021 and 2022 cash checkpoints agree within rounding using the disclosed USD
FX-fee inference. Later USD differences remain unresolved:

| Snapshot | Reconstructed minus reported USD |
|---|---:|
| 2023-12-31 | +129.15 |
| 2024-12-31 | +846.10 |
| 2025-12-31 | +1,072.40 |
| 2026-10-08 | +161.40 |

The final reconstructed USD cash is **9,994.163875393871**, versus the reported
**9,832.763875392**. EUR is zero. A negligible RUB arithmetic residual is retained,
not turned into an undocumented adjustment. Reconstructed cash therefore cannot
be described as a fully verified broker cash ledger. The supplied derived sheets
may omit cash charges/adjustments. Original statements would be needed to resolve
these differences. The dashboard displays the differences prominently and does
not silently force agreement.

Positions comparisons expose original-versus-successor ISIN differences. Original
audit findings also include canonical quantities for transferred-out lots, and
are preserved separately even where this ledger corrects their cause. Missing
2026 KZT rates are tax-only warnings here (original severity remains recorded). Cash
differences above 100 native units are blocking reconciliation findings; smaller
differences above 0.05 are warnings. Unknown basis/FX and unresolvable accounting
events block affected allocations. Inferred basis is always a warning.

## Test and verification

```powershell
.venv\Scripts\python.exe -m pytest -q --basetemp .pytest-tmp
node tools\verify_dashboard.cjs output\ib_U5157275_audit\allocation_dashboard.html
```

The Python suite covers fractional FIFO, partial/full sales, profit/loss cash,
transfers, maturities/deduplication, short collateral/close/expiry, long expiries,
FX, income and fees, borrowing, distinct trade IDs, corporate continuity, unknown
and inferred spinoff policies, weights, filters, colors and complete exports.
Integration tests use the actual supplied workbook and cached historical FX.
Final verification with optional rendering-test dependencies installed: **83 tests passed**. The IBKR provisional-spinoff output has
428 computable states and 72 distinct instruments; every full-portfolio weight
sum meets the 0.000001 percentage-point tolerance. Input SHA-256 remained unchanged.

The optional Node check executes the actual dashboard controller with DOM/Plotly
adapters to verify search, selection, both modes, highlighting, dates, CSV export
and unchanged denominators. It is a controller test, not browser rendering. The
hover regression checks also cover MTNA before and after its sale, absolute USD
cost, zero-weight exclusion, hidden legend entries and dates between events. The
computer-use environment exposed no available browser, so a real-browser visual
review could not be completed in this session. Opening the HTML in a browser is
still required to confirm the visual geometry and Plotly rendering on your screen.

The additional rendering regression runs the actual bundled Plotly engine in
jsdom with SVG text-measurement shims. It switches the full workbook chart from
73 security/cash traces to 7 asset classes and back three times, checks the SVG
legend, removes option traces, and verifies that filtering keeps the full
denominator. For all three generated dashboards it also changes every profit
currency, checks the actual Plotly values, axis/table labels and selected-currency
CSV, and confirms that switching does not mutate either ledger. Native-profit
regressions cover RUB/KZT FIFO, whole-balance conversion, mixed currencies,
missing display FX, transfers, options and independently summed workbook results.
This catches rendering errors that a Plotly adapter cannot detect.
Plotly trace UIDs encode business keys into unique CSS-safe identifiers; ISINs,
option identifiers, class names and colors remain unchanged. Rendering errors
also appear above the chart instead of silently interrupting a mode change.

To enable this optional regression (Node 18 or later):

```powershell
npm.cmd ci --prefix .qa --ignore-scripts --no-audit --no-fund
node tools\verify_plotly_render.cjs output\ib_U5157275_audit\allocation_dashboard.html
```

It is included in pytest when those dependencies are installed; otherwise that
test is skipped. Node and jsdom are not required to build or open the dashboard.

## Modules

`workbook.py` parses the actual schema and metadata; `events.py` normalizes and
deduplicates; `corporate_actions.py` resolves conversion chains; `fx.py` manages
rates/provenance; `fifo.py`, `cash.py` and `derivatives.py` maintain separate
accounting ledgers; `profit_lots.py` maintains independent native FIFO basis;
`profit.py` accumulates native realized profit and converts cumulative views;
`currency_profit.py` recognizes actual currency/debt closures without inventing
costs for ordinary cash; `profit_audit.py` verifies source coverage, native cash
and deferred capital, and the independent FIFO P/L;
`allocation.py` emits complete states; `reconciliation.py`
compares independent snapshots; `colors.py` creates the persistent palette;
`export.py` writes auditable series; `visualization.py` and `dashboard.html`
generate the offline dashboard, with `profit_ui.js` providing profit currency
controls and exports; `__main__.py` is the CLI.
