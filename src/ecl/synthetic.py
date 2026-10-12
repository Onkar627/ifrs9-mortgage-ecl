"""Synthetic files in Freddie Mac's exact layout, for tests and for a first run.

Two kinds of loans:

* EDGE CASES: 15 hand-written loan histories, each exercising one rule of the
  pipeline (a cure, a short sale, a seasoned acquisition, a maturity, COVID
  forbearance, sentinel codes, a duplicate record, a gap, an orphan...).
  tests/ and docs/WALKTHROUGH.md use them.
* RANDOM LOANS: a deliberately simple Markov simulation (current -> 30 -> 60 ->
  90+ -> liquidation, prepayment driven by refinance incentive) so the data
  quality report has realistic shape before the real files arrive.

Nothing here is calibrated to real mortgages, and every report built from it is
labelled synthetic.

Usage:  python -m ecl.synthetic data/synthetic --n-random 2000 --seed 7
"""

from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from pathlib import Path

from .layout import ORIGINATION_COLUMNS, PERFORMANCE_COLUMNS

CUTOFF = "202509"  # last reporting month in the synthetic files


# --------------------------------------------------------------------------- months
def add_months(yyyymm: str, k: int) -> str:
    idx = int(yyyymm[:4]) * 12 + int(yyyymm[4:]) - 1 + k
    return f"{idx // 12:04d}{idx % 12 + 1:02d}"


def diff_months(a: str, b: str) -> int:
    """a - b in months."""
    return (int(a[:4]) * 12 + int(a[4:])) - (int(b[:4]) * 12 + int(b[4:]))


# --------------------------------------------------------------------------- records
class Amortizer:
    """Level-payment amortisation; a missed month simply leaves the balance unchanged."""

    def __init__(self, upb: float, rate: float, term: int):
        self.balance = float(upb)
        self.r = rate / 1200
        self.payment = upb * self.r / (1 - (1 + self.r) ** -term)

    def pay(self, installments: int = 1) -> None:
        for _ in range(installments):
            self.balance = max(0.0, self.balance - (self.payment - self.balance * self.r))


def origination(loan_id: str, first_pay: str, term: int, upb: float, rate: float, **over) -> dict:
    rec = dict(
        fico=740, first_payment_date=first_pay, first_time_homebuyer="N",
        maturity_date=add_months(first_pay, term - 1), msa="19100", mi_pct=0, num_units=1,
        occupancy="P", orig_cltv=80, orig_dti=36, orig_upb=int(upb), orig_ltv=80,
        orig_rate=rate, channel="R", prepay_penalty="N", amortization_type="FRM",
        property_state="TX", property_type="SF", postal_code="750", loan_id=loan_id,
        loan_purpose="P", orig_term=term, num_borrowers=2, seller_name="OTHER",
        super_conforming="N", harp_flag="N", valuation_method=2, interest_only="N",
        vantage4=9999,
    )
    rec.update(over)
    return rec


def monthly(loan_id: str, period: str, first_pay: str, term: int, balance: float,
            status: str, rate: float, ltv_now: float | None = None) -> dict:
    age = diff_months(period, first_pay) + 1
    rec = dict(
        loan_id=loan_id, period=period, current_upb=round(balance, 2), dlq_status=status,
        loan_age=age, remaining_months=term - age, current_rate=rate,
        non_interest_bearing_upb=0, interest_bearing_upb=round(balance, 2),
        servicer_name="OTHER", mi_cancellation=7,
    )
    if status.isdigit():
        rec["ddlpi"] = add_months(period, -int(status))
    if period >= "201704" and ltv_now is not None:  # ELTV only exists from April 2017
        rec["eltv"] = max(1, round(ltv_now))
    return rec


def terminate(rec: dict, code: str, balance_before: float, losses: dict | None = None) -> dict:
    rec.update(zero_balance_code=code, zero_balance_date=rec["period"],
               zero_balance_removal_upb=round(balance_before, 2),
               current_upb=0, interest_bearing_upb=0)
    if losses:
        rec.update(losses)
        # Freddie Mac's formula: removal UPB + net sale proceeds + delinquent interest
        #                        + expenses + MI recoveries + non-MI recoveries
        rec["actual_loss"] = round(balance_before + sum(losses.values()), 2)
    return rec


def history(loan_id: str, first_pay: str, term: int, upb: float, rate: float,
            statuses: list[str], start: str | None = None, terminal: dict | None = None,
            extras: dict[str, dict] | None = None) -> list[dict]:
    """Records for one hand-written history.

    statuses  delinquency code per month from `start` ('00', '01', ..., 'RA', 'XX')
    terminal  {'code': '09', 'losses': {...}} applied to the last month
    extras    {period: {field: value}} overrides for particular months
    """
    start = start or first_pay
    am = Amortizer(upb, rate, term)
    am.pay(diff_months(start, first_pay))  # installments paid before Freddie Mac acquired it
    prev = 0
    out: list[dict] = []
    for i, status in enumerate(statuses):
        period = add_months(start, i)
        if status.isdigit():
            now = int(status)
            if now <= prev:                        # paid this month, plus any catch-up
                am.pay(prev - now + 1)
        elif status == "XX":                       # unknown status: assume paid as scheduled
            now = prev
            am.pay()
        else:                                      # 'RA': nothing paid
            now = prev + 1
        balance_before = am.balance
        rec = monthly(loan_id, period, first_pay, term, am.balance, status, rate,
                      ltv_now=80 * am.balance / upb)
        rec.update((extras or {}).get(period, {}))
        if terminal and i == len(statuses) - 1:
            terminate(rec, terminal["code"], balance_before, terminal.get("losses"))
        out.append(rec)
        prev = now
    return out


# --------------------------------------------------------------------------- edge cases
def edge_cases() -> tuple[list[dict], list[dict]]:
    """The hand-written loans. Each docstring line below is what the pipeline must do."""
    orig: list[dict] = []
    perf: list[dict] = []

    def add(loan_id, first_pay, term, upb, rate, statuses, orig_over=None, **kw):
        orig.append(origination(loan_id, first_pay, term, upb, rate, **(orig_over or {})))
        perf.extend(history(loan_id, first_pay, term, upb, rate, statuses, **kw))

    def months_between(a: str, b: str) -> int:  # inclusive count
        return diff_months(b, a) + 1

    # E01  performing all along -> 'active' (censored at the cutoff)
    add("F19Q1E000001", "201904", 360, 250_000, 4.5, ["00"] * months_between("201904", CUTOFF))

    # E02  pays off early -> 'prepay' in 2021-02
    add("F19Q1E000002", "201904", 360, 250_000, 4.5, ["00"] * 23, terminal={"code": "01"})

    # E03  30 -> 60 -> 90 (default 2009-04) -> REO -> sold at a loss in 2011-01
    add("F07Q1E000003", "200704", 360, 200_000, 6.5,
        ["00"] * 22 + ["01", "02", "03"] + [f"{k:02d}" for k in range(4, 18)] + ["RA"] * 7,
        orig_over=dict(fico=655, orig_ltv=90, orig_cltv=90, mi_pct=25, orig_dti=45),
        terminal={"code": "09", "losses": dict(
            net_sale_proceeds=-130_000.0, delinquent_accrued_interest=23_000.0,
            total_expenses=12_500.0, mi_recoveries=-20_000.0, non_mi_recoveries=-1_500.0)})

    # E04  reaches 60 days, cures, later prepays -> 'prepay' (never a default)
    add("F07Q2E000004", "200707", 360, 180_000, 6.25,
        ["00"] * 30 + ["01", "02"] + ["00"] * 28, terminal={"code": "01"})

    # E05  reaches 90 days (default 2010-08), cures, pays off in 2013-03 -> resolution 'paid_off'
    add("F07Q2E000005", "200708", 360, 210_000, 6.5,
        ["00"] * 34 + ["01", "02", "03", "02", "01"] + ["00"] * 29, terminal={"code": "01"})

    # E06  short sale while only 60 days late -> 'default' on the zero-balance month (2010-06)
    add("F08Q1E000006", "200803", 360, 190_000, 6.0,
        ["00"] * 25 + ["01", "02", "02"],
        terminal={"code": "03", "losses": dict(
            net_sale_proceeds=-140_000.0, delinquent_accrued_interest=9_000.0,
            total_expenses=6_000.0, mi_recoveries=0.0, non_mi_recoveries=-500.0)})

    # E07  15-year loan bought seasoned (first record at 6 months on book) and paid at
    #      maturity -> 'other_exit' not 'prepay'; entry_mob = 6 (left truncation)
    add("F07Q2E000007", "200706", 180, 150_000, 5.75,
        ["00"] * months_between("200711", "202205"), start="200711", terminal={"code": "01"})

    # E08  repurchased for an underwriting defect -> 'other_exit'
    add("F19Q2E000008", "201907", 360, 275_000, 4.0, ["00"] * 14,
        terminal={"code": "96"}, extras={"202008": {"defect_settlement_date": "202008"}})

    # E09  60 days late, modified in 2010-08 (loan_age restarts, rate cut), sold as a
    #      reperforming loan in 2015-03 -> 'other_exit'; months on book keep counting
    mod = {"201008": dict(modification_flag="Y", current_rate=4.0, loan_age=1, remaining_months=479)}
    for k, p in enumerate(add_months("201009", j) for j in range(55)):
        mod[p] = dict(modification_flag="P", current_rate=4.0, loan_age=k + 2, remaining_months=478 - k)
    add("F07Q3E000009", "200710", 360, 220_000, 6.75,
        ["00"] * 32 + ["01", "02"] + ["00"] * 56, terminal={"code": "16"}, extras=mod)

    # E10  COVID forbearance: missed payments from 2020-04, 90 days in 2020-06 (a default
    #      under the plain 90-day rule), payment deferral in 2021-01, current to the cutoff
    covid = {add_months("202004", j): dict(assistance_plan="F", disaster_delinquency="Y")
             for j in range(9)}
    covid["202101"] = dict(payment_deferral_flag="C", non_interest_bearing_upb=12_700.0)
    for j in range(1, 57):
        covid[add_months("202101", j)] = dict(payment_deferral_flag="P",
                                               non_interest_bearing_upb=12_700.0)
    add("F19Q3E000010", "201910", 360, 300_000, 3.9,
        ["00"] * 6 + [f"{k:02d}" for k in range(1, 10)] + ["00"] * 57, extras=covid)

    # E11  every "not available" sentinel -> NULLs in `loans`
    add("F24Q1E000011", "202403", 360, 320_000, 6.9,
        ["00"] * months_between("202403", CUTOFF),
        orig_over=dict(fico=9999, orig_ltv=999, orig_cltv=999, orig_dti=999, mi_pct=999,
                       num_units=99, occupancy="9", channel="9", property_type="99",
                       loan_purpose="9", num_borrowers=99, first_time_homebuyer="9",
                       postal_code="000", valuation_method=7))

    # E12  two months of unknown status ('XX') -> not a default
    statuses = ["00"] * months_between("202001", CUTOFF)
    statuses[diff_months("202105", "202001")] = "XX"
    statuses[diff_months("202106", "202001")] = "XX"
    add("F19Q4E000012", "202001", 360, 260_000, 3.75, statuses)

    # E13  one month delivered twice -> de-duplicated
    add("F19Q4E000013", "202001", 360, 260_000, 3.75, ["00"] * months_between("202001", CUTOFF))
    perf.append(dict(next(r for r in perf if r["loan_id"] == "F19Q4E000013"
                          and r["period"] == "202007")))

    # E14  one month missing (2021-03) while the loan is at risk -> flagged as a panel gap
    add("F19Q4E000014", "202001", 360, 260_000, 3.75, ["00"] * months_between("202001", CUTOFF))
    perf.remove(next(r for r in perf if r["loan_id"] == "F19Q4E000014" and r["period"] == "202103"))

    # E15  performance records with no origination record -> excluded from the panel
    perf.extend(history("F19Q4E000099", "202001", 360, 200_000, 3.75, ["00"] * 3))

    # E16  defaults in 2009-08, then one month of its post-default history (2009-11) is
    #      missing, as in real foreclosure histories -> counted, but not a panel gap
    add("F08Q2E000016", "200806", 360, 230_000, 6.25,
        ["00"] * 12 + ["01", "02", "03", "02", "01"] + ["00"] * 6, terminal={"code": "01"})
    perf.remove(next(r for r in perf if r["loan_id"] == "F08Q2E000016" and r["period"] == "200911"))

    return orig, perf


# --------------------------------------------------------------------------- random loans
MARKET_RATE = {  # rough 30-year mortgage rate by year, only to drive refinance incentive
    1999: 7.4, 2000: 8.0, 2001: 7.0, 2002: 6.5, 2003: 5.8, 2004: 5.8, 2005: 5.9, 2006: 6.4,
    2007: 6.3, 2008: 6.0, 2009: 5.0, 2010: 4.7, 2011: 4.5, 2012: 3.7, 2013: 4.0, 2014: 4.2,
    2015: 3.9, 2016: 3.7, 2017: 4.0, 2018: 4.5, 2019: 3.9, 2020: 3.1, 2021: 3.0, 2022: 5.3,
    2023: 6.8, 2024: 6.7, 2025: 6.6,
}
STRESS = {2008: 2.5, 2009: 4.0, 2010: 3.5, 2011: 2.5, 2012: 1.6, 2020: 2.0}  # default multiplier


def random_loans(n: int, seed: int = 7, vintages: range = range(2003, 2023)) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    orig: list[dict] = []
    perf: list[dict] = []
    ltv_choices = [60, 70, 75, 80, 85, 90, 95, 97]
    ltv_weights = [10, 12, 13, 35, 8, 10, 8, 4]
    mi_by_ltv = {85: 12, 90: 25, 95: 30, 97: 35}

    for i in range(n):
        v, q = rng.choice(list(vintages)), rng.randint(1, 4)
        loan_id = f"F{v % 100:02d}Q{q}R{i:06d}"
        first_pay = add_months(f"{v}01", 3 * (q - 1) + rng.randint(0, 2) + 2)
        if first_pay > CUTOFF:
            continue
        term = 360 if rng.random() < 0.85 else 180
        fico = int(min(830, max(580, rng.gauss(745, 45))))
        ltv = rng.choices(ltv_choices, ltv_weights)[0]
        rate = round((MARKET_RATE[v] + rng.gauss(0.25, 0.3) + (750 - fico) * 0.002) * 8) / 8
        upb = round(min(726_000, max(50_000, rng.gauss(250_000, 90_000))), -3)
        orig.append(origination(
            loan_id, first_pay, term, upb, rate, fico=fico if rng.random() > 0.01 else 9999,
            orig_ltv=ltv, orig_cltv=ltv + (5 if rng.random() < 0.1 else 0),
            orig_dti=int(rng.uniform(15, 50)), mi_pct=mi_by_ltv.get(ltv, 0),
            loan_purpose=rng.choice("PPPCN"), property_state=rng.choice(["CA", "TX", "FL", "NY", "IL", "AZ"]),
        ))

        am = Amortizer(upb, rate, term)
        start = add_months(first_pay, rng.randint(1, 6)) if rng.random() < 0.08 else first_pay
        am.pay(diff_months(start, first_pay))
        state, period = 0, start
        while period <= CUTOFF:
            year = int(period[:4])
            age = diff_months(period, first_pay) + 1
            u = rng.random()
            code, losses, balance_before = None, None, am.balance
            if state == 0:
                incentive = rate - MARKET_RATE.get(year, 6.6)
                p_prepay = 0.003 + 0.035 / (1 + math.exp(-3 * (incentive - 0.75)))
                p_miss = min(0.2, 0.0012 * STRESS.get(year, 1.0) * math.exp((720 - fico) / 60)
                             * (1 + max(0, ltv - 80) / 15))
                if age >= term:
                    code = "01"                      # final scheduled payment
                elif u < p_prepay:
                    code = "01"
                elif u < p_prepay + p_miss:
                    state = 1
                else:
                    am.pay()
            elif state in (1, 2):
                if u < 0.4:
                    am.pay(state + 1)
                    state = 0
                else:
                    state += 1
            else:
                if u < 0.04:
                    am.pay(state + 1)
                    state = 0
                elif state >= 6 and u < 0.04 + 0.06:
                    code = "09" if rng.random() < 0.7 else "03"
                    severity = rng.uniform(0.15, 0.55) * (1.25 if 2009 <= year <= 2011 else 1.0)
                    bal = am.balance
                    mi = mi_by_ltv.get(ltv, 0) / 100
                    losses = dict(
                        net_sale_proceeds=-round(bal * (1 - severity), 2),
                        delinquent_accrued_interest=round(bal * rate / 1200 * state, 2),
                        total_expenses=round(bal * 0.06, 2),
                        mi_recoveries=-round(min(mi * bal, bal * severity), 2),
                        non_mi_recoveries=-500.0,
                    )
                else:
                    state += 1
            status = f"{min(state, 99):02d}"
            rec = monthly(loan_id, period, first_pay, term, am.balance, status, rate,
                          ltv_now=ltv * am.balance / upb)
            if code:
                perf.append(terminate(rec, code, balance_before, losses))
                break
            perf.append(rec)
            period = add_months(period, 1)
    return orig, perf


# --------------------------------------------------------------------------- writing
def write_files(out_dir: str | Path, orig: list[dict], perf: list[dict]) -> list[Path]:
    """Write sample_orig_YYYY.txt / sample_perf_YYYY.txt per vintage (pipe-delimited, no header)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def vintage(loan_id: str) -> int:
        yy = int(loan_id[1:3])
        return (1900 if yy >= 90 else 2000) + yy

    def line(columns: list[str], rec: dict) -> str:
        return "|".join("" if rec.get(c) is None else str(rec[c]) for c in columns)

    groups: dict[int, dict[str, list[str]]] = defaultdict(lambda: {"orig": [], "perf": []})
    for rec in orig:
        groups[vintage(rec["loan_id"])]["orig"].append(line(ORIGINATION_COLUMNS, rec))
    for rec in perf:
        groups[vintage(rec["loan_id"])]["perf"].append(line(PERFORMANCE_COLUMNS, rec))

    written = []
    for year, parts in sorted(groups.items()):
        for kind in ("orig", "perf"):
            path = out_dir / f"sample_{kind}_{year}.txt"
            path.write_text("\n".join(parts[kind]) + "\n", encoding="utf-8")
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write synthetic Freddie Mac-format files.")
    parser.add_argument("out_dir", nargs="?", default="data/synthetic")
    parser.add_argument("--n-random", type=int, default=2000, help="random loans on top of the edge cases")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    orig, perf = edge_cases()
    if args.n_random:
        o, p = random_loans(args.n_random, args.seed)
        orig += o
        perf += p
    files = write_files(args.out_dir, orig, perf)
    print(f"Wrote {len(orig):,} loans and {len(perf):,} monthly records to "
          f"{len(files)} files in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
