# Read-only workbook inspection

## Additional Tsifra input

`files/tsifra_1432280_audit.xlsx` has the same sheet/column layout, but includes
`Transfers.Transfer_Type = tax`: 21 outgoing payments and one incoming refund.
These are independent cash-tax postings; dividend/coupon net amounts
already include the withholding recorded on their own rows.

The corrected file (SHA-256
`36cb091a0e7142902ce5d3c89e873f80e5fb7db1ec2c5fe854acb69e6338ebd1`)
contains 406 trades, 51 transfers, 16 dividends, 22 coupons, four
interest records, and no corporate actions. The nine incoming transfer lots
on 2024-02-01 have original purchase dates and costs in FIFO. GMKN is split
into 17 and 6 shares; SNGSP into two 15,000-share lots. Match by ISIN plus
original acquisition timestamp; summing both lots before matching a single
transfer incorrectly loses the known basis. Keep original purchase dates for
FIFO and historical USD conversion, and prevent reuse of matched source rows.
Four repo-interest records contain separate
commissions of RUB 0.01 each, excluded from their supplied `Net_Amount`.

The earlier version had seven transfers and undated zero-cost FIFO placeholders.
That historical missing-data case is retained as a synthetic regression, not
reported as an issue in the corrected workbook. The FX cache was extended for
the new event dates; no rate-of-one or invented cash adjustments are used.

## Additional Halyk input

`files/halyk_1028197847_audit.xlsx` SHA-256:
`e13717afcd4fe7b7bffd6453afa238c16284e75f1960053f37fc5c4e8e812a66`.
It contains 42 trades (including ten `redemption` rows), ten supplementary
`CorporateActions.maturity` records, five coupons, 23 FIFO closing fragments,
19 position records, two final cash snapshots and no transfer records.

The ten redemptions and ten maturities are the same ten events. Their signed
quantities, proceeds, currencies, dates and ISINs match. Using both creates
artificial security shorts and duplicate cash proceeds. Deduplication keeps the
trade's original fee and attaches the corporate source reference.

BIGDb6 is denominated in KZT; both its acquisition and partial sales have known
costs. Daily KZT/USD is obtained from NBK dated RSS and cached independently of
the audit's annual KZT tax fields. The description metadata explicitly names
Treasury bills and TSY inflation-linked notes for asset-class identification.

Position quantities reconcile after the duplicate maturities are removed.
Cash cannot reconcile from the supplied events alone: the entire funding history
is absent. Negative replayed cash is a missing-funding diagnostic, not confirmed
broker borrowing. Original records are needed to restore cash allocation; no
balancing cash movement is created.

## Current IBKR schema

Source: `files/ib_U5157275_audit.xlsx`.
SHA-256: `c6ebe8e68d5c9687307aa28b0d0a0582288ff2f36b830c878fbe2969e67a85ec`.

The workbook has header rows followed by records, except `Years_Results`, which
contains tax summary sections and is not an account ledger.

| Sheet | Records | Relevant fields |
|---|---:|---|
| Trades | 196 | Date_Time, Trade_ID, Trade_Type, Symbol, ISIN, Asset_Type, signed Quantity, Price, Multiplier, positive Amount, Commission, Amount_With_Commission, Currency |
| Transfers | 24 | Date, Transfer_Type, Direction, Quantity, Enter_Date, Price, Amount, Counterparty |
| CorporateActions | 33 | Date, ISIN, Action_Type, Description, Quantity, Proceeds, Value, Realized_Pl |
| Dividends | 111 | Date, Pay_Date, Gross_Amount, Withholding_Tax, Net_Amount, Currency |
| Coupons | 182 | Date, Gross_Amount, Withholding_Tax, Net_Amount, Is_Revert, Currency |
| Interest | 67 | Date, Description, Financing_Kind, Net_Amount, Commission, Currency |
| CashBalances | 9 | Date, Currency, Ending_Cash, Source_Report |
| Fifo | 116 | Enter_Date, Enter_Quantity, Enter_Amount, Enter_Commission, Exit_Date, Source_Trade_ID |
| Positions | 173 | Year, Date, ISIN, Quantity, Price, Multiplier, Amount |
| Instruments | 170 | ISIN, Conid, Symbol, Description, Type, Multiplier, Expiry, Strike, Underlying, As_Of_Date |
| Unprocessed | 3 | Severity, Reason, Details, source references |
| Reconciliation | 449 | Metric, Severity, Broker_Value, Canonical_Value, Difference, Instrument_Key, Year |

## Observed events and material ambiguities (before implementation)

* First account event is a USD 100,000 deposit on 2021-11-22. No earlier opening
  cash is supplied. Early RUB purchases are financed by negative RUB cash.
* Trades: 171 ordinary trades, 13 maturities, 9 full calls, 2 option expirations,
  1 spinoff. Asset types include stocks, bonds, Treasury bills, Forex, equity/index
  options and options on futures. Amount is unsigned; Amount_With_Commission adds
  fees even on sales and must not be used as sale proceeds.
* All 22 maturity/full-call records are duplicated between Trades and
  CorporateActions. Supplementary records must not generate extra cash.
* Transfers include 9 cash entries (including a fee refund), 14 outgoing security
  lots, and the incoming USD 200,000-face Treasury bill US912797FS14 on 2023-10-23.
  The current FIFO records provide documented USD 191,472.70 acquisition cost
  and original acquisition timestamp 2023-07-13 16:52:52. An earlier workbook
  version supplied USD 193,153.33 inferred basis without an acquisition date;
  that earlier estimate is not used for the corrected input. No cash movement
  is created by the transfer.
* Seven Forex rows are currency exchanges, not assets. No commission currency is
  supplied. In particular the small USD.RUB trade has a fee of 2: currency is
  ambiguous. Subsequent reconstruction shows that USD fee treatment explains
  equal/opposite RUB 2 and USD 2 checkpoint differences. Default USD fee currency
  is therefore a disclosed inference; quote-currency treatment is configurable.
* Dividends, coupons and interest contain signed net cash. Negative coupons are
  accrued-interest payments/adjustments, not negative bond acquisition costs.
* Instruments matches options by Description as well as Symbol; the identifiers
  in Trades and Instruments have different formats. GLD short put multiplier is
  100, strike 251. Futures-option multiplier is 125,000.
* ERUS trades were retrospectively relabeled US464ESC0112 even before the
  2022-08-16 merger. The original ISIN is US46434G7988. AVGO and IPG trades also
  use successor ISINs before their tender/merger dates. One-for-one corporate
  chains can restore historical identities while retaining original row evidence.
* The ERUS merger has USD 61.7103 cash proceeds missing from Trades; include this
  independently identified CorporateActions cash once. Do not treat Value as cash.
* AT&T/WBD spinoff supplies child quantity but no allocation percentage. Do not
  infer a precise basis from zero-price synthetic trades. Preserve the parent's
  basis provisionally and mark both positions as having unresolved basis until
  liquidated. The chart/CSV must distinguish unknown basis from zero. An explicit
  optional `broker-pl` policy can infer USD 537.71648796 from WBD's complete later
  sale and broker P/L, corroborated by the equal/opposite AT&T discrepancy. This
  uses later evidence retrospectively and remains labeled inferred, not verified.
* Positions is a derived acquisition-lot schedule, not an independent broker
  statement. Sum its rows per date/instrument for quantity reconciliation and
  additionally surface original broker-versus-canonical Reconciliation findings.
* Positions labels 2026 holdings as 2026-12-31 although source account data ends
  2026-10-08 (CashBalances and Instruments.As_Of_Date). Treat those as forward
  labels, compare with the final available state with a warning, and end the
  historical chart on 2026-10-08 without future FX or invented events.
* KZT fields are tax conversions, not USD FX. Missing 2026 KZT rates are a tax-only
  warning for this dashboard. Daily USD FX requires an independent historical
  source and an auditable local cache. Missing FX blocks the affected valuation.

Date-only external transfers/openings are ordered at 00:00; date-only income is
at 23:59; corporate actions use the audit's 20:25 convention when there is no
timestamp. Actual trade timestamps take precedence. Within a timestamp use
source priority and row number; emit one state after the whole group, retaining
each underlying event for drill-down. These conventions cannot establish unknown
intraday settlement order.
