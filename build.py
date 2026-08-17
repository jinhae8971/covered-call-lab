#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
커버드콜 ETF 리서치 대시보드 빌더
====================================
universe.json (메타데이터) + 시장 데이터(야후/네이버) → dashboard.html (단일 파일)

설계 원칙
  - 데이터 레이어(수집)와 뷰 레이어(HTML)를 분리한다.
  - 결과물은 단일 HTML 파일이다. CORS나 로컬서버 없이 더블클릭으로 열린다.
  - 실패한 종목이 있어도 전체가 죽지 않는다.
  - 모든 수치에는 기준일이 붙는다.
  - 절대수익이 아니라 '원지수 대비 초과수익'으로 평가한다. 시장 국면 효과를 제거하기 위함.

사용법
  python build.py                  # 전체 갱신
  python build.py --cache          # data/raw_cache.json 재사용 (오프라인 재렌더)
  python build.py --only-us        # 미국만
  python build.py --only-kr        # 한국만
"""

from __future__ import annotations
import argparse, json, math, os, re, sys, time, datetime as dt
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
UNIVERSE = os.path.join(ROOT, "universe.json")
CACHE = os.path.join(DATA_DIR, "raw_cache.json")
# 국내 ETF 회차별 분배 이력. 네이버는 TTM 합계만 주므로 야후에서 따로 받는다.
KRDIV = os.path.join(DATA_DIR, "krdiv.json")
METRICS = os.path.join(DATA_DIR, "metrics.json")
OUT_HTML = os.path.join(ROOT, "dashboard.html")
# GitHub Pages 는 디렉터리 진입 시 index.html 을 찾는다. 같은 내용을 두 벌 쓴다.
OUT_INDEX = os.path.join(ROOT, "index.html")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TODAY = dt.date.today()


# ══════════════════════════════════════════════ HTTP

def http_json(url, tries=4, sleep=1.5):
    last = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/plain,*/*"})
            with urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except (HTTPError, URLError, ValueError) as e:
            last = e
            time.sleep(sleep * (i + 1))
    raise RuntimeError(f"fetch 실패: {url} ({last})")


def http_text(url, tries=4, sleep=1.5):
    last = None
    for i in range(tries):
        try:
            req = Request(url, headers={"User-Agent": UA})
            with urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except (HTTPError, URLError) as e:
            last = e
            time.sleep(sleep * (i + 1))
    raise RuntimeError(f"fetch 실패: {url} ({last})")


# ══════════════════════════════════════════════ 지표 계산

def _mdd(series):
    """최대낙폭(%). series 는 (date, value) 오름차순 리스트."""
    peak, worst = None, 0.0
    for _, v in series:
        if not v or v <= 0:
            continue
        peak = v if peak is None else max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return round(worst * 100, 2)


def _slice_from(series, days):
    if not series:
        return []
    cutoff = series[-1][0] - dt.timedelta(days=days)
    return [p for p in series if p[0] >= cutoff]


def _ret(series):
    if len(series) < 2 or not series[0][1]:
        return None
    return series[-1][1] / series[0][1] - 1.0


def _cagr(series):
    if len(series) < 2 or not series[0][1]:
        return None
    yrs = (series[-1][0] - series[0][0]).days / 365.25
    if yrs < 0.25:
        return None
    return (series[-1][1] / series[0][1]) ** (1 / yrs) - 1.0


def _pct(x, nd=2):
    return None if x is None else round(x * 100, nd)


def _vol(series):
    vals = [v for _, v in series if v]
    if len(vals) < 30:
        return None
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1]]
    if len(rets) < 30:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(252) * 100, 2)


# ══════════════════════════════════════════════ 미국 (Yahoo Finance)

def fetch_us(ticker):
    # 주의: range=max 를 쓰면 야후가 장기 종목을 조용히 '월봉'으로 다운샘플링한다
    # (QQQ 기준 6,896개 → 330개). MDD·1년수익률이 크게 왜곡되므로 period1/period2 를 명시한다.
    now = int(time.time())
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1=0&period2={now}&interval=1d&events=div%2Csplit&includeAdjustedClose=true")
    res = http_json(url)["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    divs = (res.get("events") or {}).get("dividends") or {}

    px, tr = [], []
    for t, c, a in zip(ts, close, adj):
        d = dt.datetime.utcfromtimestamp(t).date()
        if c:
            px.append((d.isoformat(), c))
        if a:
            tr.append((d.isoformat(), a))
    dv = sorted((dt.datetime.utcfromtimestamp(v["date"]).date().isoformat(), v["amount"])
                for v in divs.values())
    return {"price": px, "tr": tr, "div": dv, "currency": res["meta"].get("currency", "USD")}


def compute_us(meta, raw):
    D = dt.date.fromisoformat
    px = [(D(d), v) for d, v in raw["price"]]
    tr = [(D(d), v) for d, v in raw["tr"]]
    dv = [(D(d), v) for d, v in raw["div"]]
    if not px or not tr:
        return {**meta, "status": "no-data"}

    last_d, last_px = px[-1]
    ttm_div = sum(a for d, a in dv if d > last_d - dt.timedelta(days=365))
    ytd = [p for p in tr if p[0] >= dt.date(last_d.year, 1, 1)]
    spark = [round(v, 4) for _, v in tr[::max(1, len(tr) // 120)]]

    return {
        **meta,
        "status": "ok", "id": meta["ticker"], "market": "US",
        "asof": last_d.isoformat(),
        "price": round(last_px, 2),
        "ttm_yield": round(ttm_div / last_px * 100, 2) if last_px else None,
        "ttm_dps": round(ttm_div, 4),
        "pay_count_ttm": sum(1 for d, _ in dv if d > last_d - dt.timedelta(days=365)),
        "tr_ytd": _pct(_ret(ytd)),
        "tr_1y": _pct(_ret(_slice_from(tr, 365))),
        "tr_3y": _pct(_cagr(_slice_from(tr, 365 * 3))),
        "tr_5y": _pct(_cagr(_slice_from(tr, 365 * 5))),
        "tr_si": _pct(_cagr(tr)),
        "px_si": round((last_px / px[0][1] - 1) * 100, 2),
        "px_1y": _pct(_ret(_slice_from(px, 365))),
        "mdd_si": _mdd(tr),
        "mdd_1y": _mdd(_slice_from(tr, 365)),
        "mdd_basis": "총수익(배당재투자) 기준",
        "vol_1y": _vol(_slice_from(tr, 365)),
        "data_start": px[0][0].isoformat(),
        "spark": spark,
        "ccy": raw.get("currency", "USD"),
        "sched": _sched_from_history(dv, last_d, ttm_div, raw.get("currency", "USD")),
        "divhist": _divhist(dv),
        "_tr": [(d.isoformat(), v) for d, v in _slice_from(tr, 365 * 3 + 40)],
        "_px": [(d.isoformat(), v) for d, v in _slice_from(px, 365 * 3 + 40)],
    }


# ══════════════════════════════════════════════ 한국 (네이버 금융)

def fetch_kr_unadjusted(code):
    """국내 ETF의 '미수정' 일별 종가.

    왜 야후를 쓰는가:
      네이버의 일별시세는 경로(siseJson / fchart requestType=0 / 모바일 price API)를
      가리지 않고 전부 '수정주가'다. 세 경로의 값이 소수점까지 일치하는 것을 확인했고,
      441680 은 2022-09-22 에 10,000원으로 상장했는데 네이버 시계열 첫값이 6,328원이다.
      즉 분배락이 소급 반영된 총수익 시계열이라 '배당 제외 가격'을 뽑아낼 수 없다.
      야후는 같은 종목을 close(미수정) / adjclose(수정) 두 벌로 주므로 여기서만 가져온다.
    실패해도 예외를 던지지 않는다. 가격축은 부가 기능이고, 없으면 총수익축으로 대체한다.
    """
    now = int(time.time())
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{code}.KS"
           f"?period1={now - 86400 * 1300}&period2={now}&interval=1d")
    try:
        res = http_json(url, tries=2, sleep=1.0)["chart"]["result"][0]
        ts, close = res["timestamp"], res["indicators"]["quote"][0]["close"]
        out = [(dt.datetime.utcfromtimestamp(t).date().isoformat(), c)
               for t, c in zip(ts, close) if c]
        return out if len(out) >= 60 else None
    except Exception:
        return None


def fetch_kr_dividends(code):
    """국내 ETF의 회차별 분배 이력(기준일, 주당금액).

    네이버 etfAnalysis 는 dividendPerShareTtm(합계)과 지급월 목록만 준다.
    회차별 금액이 없으면 '분배금이 늘고 있는지 줄고 있는지'를 판정할 수 없다.
    야후는 .KS 심볼에 대해 events=div 로 회차별 배당락일과 금액을 주므로 여기서 받는다.
    실패해도 예외를 던지지 않는다. 없으면 기존 관행 규칙으로 되돌아간다.
    """
    now = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.KS"
           f"?period1=0&period2={now}&interval=1d&events=div")
    try:
        res = http_json(url, tries=2, sleep=1.0)["chart"]["result"][0]
        dv = (res.get("events") or {}).get("dividends") or {}
        return sorted([dt.datetime.utcfromtimestamp(int(v["date"])).date().isoformat(),
                       round(float(v["amount"]), 4)] for v in dv.values())
    except Exception:
        return None


def fetch_kr(code):
    an = http_json(f"https://m.stock.naver.com/api/stock/{code}/etfAnalysis")
    start = (TODAY - dt.timedelta(days=365 * 12)).strftime("%Y%m%d")
    end = TODAY.strftime("%Y%m%d")
    raw = http_text(f"https://api.finance.naver.com/siseJson.naver?symbol={code}"
                    f"&requestType=1&startTime={start}&endTime={end}&timeframe=day")
    rows = json.loads(raw.replace("'", '"').strip())
    px = []
    for r in rows[1:]:
        try:
            d = dt.datetime.strptime(str(r[0]), "%Y%m%d").date()
            c = float(r[4])
            if c > 0:
                px.append((d.isoformat(), c))
        except Exception:
            continue
    return {"analysis": an, "price": px, "price_unadj": fetch_kr_unadjusted(code)}


def _kr_num(s):
    """'2,977억' → 2977.0 (억원)"""
    if not s:
        return None
    m = re.sub(r"[^0-9.]", "", str(s))
    return float(m) if m else None


def _kr_px_series(unadj, tr_series):
    """배당 제외 가격축. 야후 미수정 종가가 없으면 총수익축으로 우아하게 후퇴한다."""
    if not unadj:
        return [(d.isoformat(), v) for d, v in _slice_from(tr_series, 365 * 3 + 40)]
    pts = [(dt.date.fromisoformat(d), v) for d, v in unadj]
    return [(d.isoformat(), v) for d, v in _slice_from(pts, 365 * 3 + 40)]


def compute_kr(meta, raw):
    an = raw.get("analysis") or {}
    px = [(dt.date.fromisoformat(d), v) for d, v in raw["price"]]
    if not px:
        return {**meta, "status": "no-data"}

    last_d, last_px = px[-1]
    div = an.get("dividend") or {}
    ttm_y = div.get("dividendYieldTtm")
    ttm_dps = div.get("dividendPerShareTtm")
    perf = {p["periodTypeCode"]: p["value"] for p in (an.get("returnPerformanceList") or [])}

    # ── 중요 ──────────────────────────────────────────────────────────
    # 네이버 siseJson 은 '수정주가'를 준다. 즉 과거 가격이 분배락만큼 소급
    # 하향 조정돼 있어 시계열 자체가 이미 '분배금 재투자 총수익' 이다.
    #   근거: 491620 은 2024-10-02 에 10,000원으로 상장했는데 시계열 첫값이
    #        6,812원, 마지막값 10,970원 ≈ 현재 NAV 10,984원.
    # 따라서 여기에 TTM 분배율을 더하면 분배금을 두 번 세게 된다.
    # (이전 버전의 버그: 커버드콜이 원지수를 +27%p 이기는 불가능한 결과가 나옴)
    s1y = _slice_from(px, 365)
    tr_1y = round((last_px / s1y[0][1] - 1) * 100, 2) if len(s1y) > 2 else perf.get("Y1")

    yrs = (last_d - px[0][0]).days / 365.25
    tr_si = tr_3y = None
    if yrs >= 0.5:
        tr_si = round(((last_px / px[0][1]) ** (1 / yrs) - 1) * 100, 2)
    s3 = _slice_from(px, 365 * 3)
    if len(s3) > 200:
        y3 = (s3[-1][0] - s3[0][0]).days / 365.25
        if y3 >= 1:
            tr_3y = round(((s3[-1][1] / s3[0][1]) ** (1 / y3) - 1) * 100, 2)

    # 원금 훼손 추정: 국내 ETF 는 관례상 10,000원(일부 5,000원)에 상장한다.
    # 수정주가 시계열로는 알 수 없으므로 상장기준가 대비 현재가로 근사한다.
    base = 5000.0 if last_px < 4000 else 10000.0
    px_si = round((last_px / base - 1) * 100, 2)

    ytd_s = [p for p in px if p[0] >= dt.date(last_d.year, 1, 1)]
    tr_ytd = round((last_px / ytd_s[0][1] - 1) * 100, 2) if len(ytd_s) > 2 else perf.get("YTD")

    listed = an.get("listedDate")
    listed_iso = f"{listed[:4]}-{listed[4:6]}-{listed[6:]}" if listed and len(listed) == 8 else None

    return {
        **meta,
        "status": "ok", "id": meta["code"], "ticker": meta["code"], "market": "KR",
        "asof": last_d.isoformat(),
        "name": an.get("itemName") or meta.get("name"),
        "issuer": an.get("issuerName") or meta.get("issuer"),
        "inception": listed_iso,
        "er": an.get("totalFee"),
        "index": an.get("etfBaseIndex"),
        "aum_bil_krw": _kr_num(an.get("marketValue")),
        "nav": an.get("nav"),
        "price": last_px,
        "ttm_yield": ttm_y,
        "ttm_dps": ttm_dps,
        "pay_count_ttm": div.get("dividendCountThisYear"),
        "tr_ytd": tr_ytd,
        "tr_1y": tr_1y,
        "tr_3y": tr_3y,
        "tr_si": tr_si,
        "px_si": px_si,
        "px_si_basis": "상장기준가 대비 현재가(원금 훼손 근사)",
        "px_1y": round(tr_1y - (ttm_y or 0), 2) if tr_1y is not None else None,
        "mdd_si": _mdd(px),
        "mdd_1y": _mdd(s1y),
        "mdd_basis": "총수익(수정주가) 기준",
        "vol_1y": _vol(s1y),
        "data_start": px[0][0].isoformat(),
        "tax": "배당소득세 15.4% · 매매차익도 배당소득 과세 · 금융소득종합과세 합산",
        "spark": [round(v, 2) for _, v in px[::max(1, len(px) // 120)]],
        "ccy": "KRW",
        "sched": _kr_sched(raw.get("dividends"), div, ttm_dps, last_d),
        "divhist": _divhist([(d, a) for d, a in (raw.get("dividends") or [])]),
        "_tr": [(d.isoformat(), v) for d, v in _slice_from(px, 365 * 3 + 40)],
        "_px": _kr_px_series(raw.get("price_unadj"), px),
        "px_src": "야후 미수정 종가" if raw.get("price_unadj") else "가격축 없음(총수익축 대체)",
    }


def _divhist(dv, years=3, cap=170):
    """최근 3년 분배 이력. 화면의 '주당 분배금 추이' 판정 근거다.

    회차 수가 아니라 기간으로 자르는 이유: 주간 배당(QDTE·YMAX 등)을 26회로 자르면
    반년치밖에 남지 않아 전년 대비 비교가 불가능해진다. 기간을 고정해야
    주간·월간·분기 종목을 같은 잣대로 볼 수 있다. cap 은 HTML 비대화 방지용이다.
    """
    if not dv:
        return []
    norm = [(d if isinstance(d, dt.date) else dt.date.fromisoformat(d), float(a))
            for d, a in dv]
    cut = norm[-1][0] - dt.timedelta(days=365 * years + 10)
    keep = [(d, a) for d, a in norm if d > cut][-cap:]
    return [[d.isoformat(), round(a, 4)] for d, a in keep]


# ══════════════════════════════════════════════ 분배 스케줄 · 공통 축

def _sched_from_history(dv, last_d, ttm_total, ccy):
    """실제 분배 이력에서 '향후 12개월 월별 분배 배분 가중치'를 만든다.

    annual 은 TTM 실적을 그대로 쓴다. 미래 분배금은 옵션 프리미엄에 따라
    변동하므로 추정 모델을 얹기보다 최근 12개월 실적을 중립적 기준선으로
    두는 편이 오차가 작고 해석도 명확하다.
    """
    ttm = [(d, a) for d, a in dv if d > last_d - dt.timedelta(days=365)]
    if not ttm or not ttm_total:
        return None
    w = {}
    for d, a in ttm:
        w[str(d.month)] = w.get(str(d.month), 0.0) + a
    tot = sum(w.values()) or 1.0
    w = {k: round(v / tot, 4) for k, v in w.items()}
    n = len(ttm)
    freq = "주간" if n >= 40 else "월간" if n >= 10 else "분기" if n >= 3 else "연간"
    # 실제 분배기준일(ex-date) 이력. 다음 지급일 추정의 앵커로 쓴다.
    # 야후가 주는 것은 배당락일이며 실지급일은 통상 1~5영업일 뒤다. 그 시차는 화면에서 밝힌다.
    ex = [d.isoformat() for d, _ in ttm][-8:]
    return {"ccy": ccy, "annual": round(ttm_total, 4), "months": w,
            "pays": n, "freq": freq, "basis": "실제 분배 이력(TTM)",
            "exdates": ex, "last_ex": ex[-1] if ex else None,
            "anchor": "exdate", "paylag": 3}


def _kr_sched(divs, div_meta, ttm_dps, last_d):
    """국내 ETF 분배 스케줄.

    1순위: 야후의 실제 분배기준일 이력. 지급일 추정 오차가 관행 규칙보다 작다.
    2순위: 네이버 지급월 패턴 + 국내 관행(지급월 말 영업일 기준 · 2영업일 내 지급).

    다만 야후의 국내 ETF 배당 데이터는 누락 회차가 있는 경우가 관측된다.
    그래서 야후 TTM 합계가 네이버 dividendPerShareTtm 과 25% 넘게 어긋나면
    이력을 신뢰하지 않고 규칙으로 되돌린다. 틀린 정밀도보다 정직한 근사가 낫다.
    """
    fallback = _sched_from_months(div_meta.get("dividendMonthThisYear"),
                                  div_meta.get("dividendCountThisYear"),
                                  ttm_dps, "KRW", last_d)
    if not divs:
        return fallback
    dv = [(dt.date.fromisoformat(d), float(a)) for d, a in divs]
    ttm = [(d, a) for d, a in dv if d > last_d - dt.timedelta(days=365)]
    y_ttm = sum(a for _, a in ttm)
    if not ttm or not ttm_dps or not y_ttm:
        return fallback
    if abs(y_ttm - float(ttm_dps)) / float(ttm_dps) > 0.25:
        return fallback
    sc = _sched_from_history(dv, last_d, y_ttm, "KRW")
    if not sc:
        return fallback
    # 야후가 주는 날짜는 배당락일이다. 국내 ETF 는 통상 배당락 다음 영업일이 기준일이고
    # 지급은 기준일로부터 2영업일 안이다. 합쳐 영업일 3일로 둔다.
    sc.update({"paylag": 3, "basis": "실제 분배 이력(TTM · 야후)",
               "annual": round(float(ttm_dps), 2),
               "src_note": "네이버 TTM 합계로 금액을 맞추고, 날짜는 야후 실적 기준일을 썼습니다."})
    return sc


def _sched_from_months(month_csv, count, ttm_dps, ccy, asof):
    """국내 ETF: 네이버가 개별 분배 이력을 주지 않아 지급 패턴으로 근사한다.

    주의: dividendMonthThisYear 는 '올해 지급된 월'이라 연중에는 잘린 목록이다.
    예를 들어 8월 초 시점의 월배당 ETF 는 "1,2,3,4,5,6,7" 로 나온다. 이를
    그대로 쓰면 8~12월 배당이 0으로 계산되는 치명적 오류가 난다.
    그래서 '올해 경과 개월수 대비 지급 횟수'로 실제 주기를 역산한다.
    """
    if not ttm_dps:
        return None
    months = [int(m) for m in re.findall(r"\d+", str(month_csv or "")) if 1 <= int(m) <= 12]
    n_ytd = int(count or len(months) or 0)
    elapsed = max(1, asof.month - 1) if asof.day < 15 else asof.month
    rate = (n_ytd / elapsed) if n_ytd else (len(months) / elapsed if months else 1.0)

    if rate >= 3.0:
        freq, per_year, pay_months = "주간", round(rate * 12), list(range(1, 13))
    elif rate >= 0.8:
        freq, per_year, pay_months = "월간", 12, list(range(1, 13))
    elif rate >= 0.25:
        freq, per_year = "분기", 4
        anchor = (months[0] % 3) if months else 3
        pay_months = [m for m in range(1, 13) if m % 3 == anchor]
    else:
        freq, per_year = "연간", 1
        pay_months = months[:1] or [12]

    w = {str(m): round(1.0 / len(pay_months), 4) for m in pay_months}
    # 네이버는 개별 분배 이력의 '날짜'를 주지 않는다. 국내 ETF 관행을 규칙으로 적는다.
    #   분배기준일 = 해당 월 마지막 영업일, 실지급 = 기준일 + 2영업일 이내
    # 운용사·상품별로 15일 기준일을 쓰는 예외가 있어 화면에서 '규칙 추정'임을 밝힌다.
    return {"ccy": ccy, "annual": round(float(ttm_dps), 2), "months": w,
            "pays": per_year, "freq": freq,
            "basis": "TTM 주당분배금 균등 배분(회차별 편차 미반영)",
            "paymonths": pay_months, "anchor": "eom", "paylag": 2,
            "rule": "국내 관행: 매 지급월 마지막 영업일 분배기준일, 2영업일 내 지급"}


def build_axis(rows, years=3):
    """모든 종목이 공유하는 '주간 날짜 축'을 만들고 각 행을 여기에 정렬한다.

    종목마다 상장일·거래일이 달라 그대로 겹쳐 그리면 x축이 어긋난다.
    공통 축에 맞춰 전방보간(forward-fill)해두면 클라이언트에서 포트폴리오
    합성 곡선을 단순 가중합으로 계산할 수 있다. 데이터가 없는 구간은 null.

    두 벌을 만든다.
      ax  ← _tr : 분배금 재투자 총수익 (배당 포함)
      axp ← _px : 미수정 종가        (배당 제외, 주가 자체의 궤적)
    커버드콜은 이 둘의 격차가 곧 '분배금으로 나간 몫'이라 나란히 봐야 판단이 선다.
    """
    ends = [dt.date.fromisoformat(r["_tr"][-1][0]) for r in rows if r.get("_tr")]
    if not ends:
        return []
    end = max(ends)
    start = end - dt.timedelta(days=365 * years)
    axis, d = [], start
    while d <= end:
        axis.append(d)
        d += dt.timedelta(days=7)
    axis_iso = [d.isoformat() for d in axis]

    def align(ser):
        """(date,val) 시계열을 공통 축에 전방보간하고 첫 유효값=100 으로 정규화."""
        if not ser:
            return None
        pts = [(dt.date.fromisoformat(x), v) for x, v in ser]
        out, i, cur = [], 0, None
        for a in axis:
            while i < len(pts) and pts[i][0] <= a:
                cur = pts[i][1]
                i += 1
            # 축 시작이 상장 이전이면 값이 없다 → null 로 둬서 차트가 끊기게 한다
            out.append(None if cur is None or a < pts[0][0] else cur)
        base = next((v for v in out if v), None)
        if not base:
            return None
        return [None if v is None else round(v / base * 100, 2) for v in out]

    for r in rows:
        tr, px = r.pop("_tr", None), r.pop("_px", None)
        if not tr:
            continue
        r["ax"] = align(tr)
        # 가격축은 총수익축과 같은 시작점을 공유해야 두 선의 격차가 곧 분배금이 된다.
        # align() 이 각자 첫값을 100 으로 잡으므로 이미 같은 출발선이다.
        r["axp"] = align(px) or r["ax"]
    return axis_iso


def fetch_fx():
    """USD/KRW. 미국 상장분을 원화로 환산해 포트폴리오를 합산하기 위해 필요하다."""
    try:
        now = int(time.time())
        url = ("https://query2.finance.yahoo.com/v8/finance/chart/KRW=X"
               f"?period1={now - 86400 * 10}&period2={now}&interval=1d")
        res = http_json(url)["chart"]["result"][0]
        vals = [v for v in res["indicators"]["quote"][0]["close"] if v]
        return round(vals[-1], 2) if vals else None
    except Exception:
        return None


# ══════════════════════════════════════════════ 벤치마크 대비 평가

def attach_benchmark(rows):
    """각 종목을 자기 원지수와 비교한다.

    이 단계가 없으면 '한국 증시가 1년에 +130% 올랐다'는 국면 효과가
    종목의 실력으로 잘못 잡힌다. 커버드콜 평가의 핵심은 절대수익이 아니라
    '원지수를 얼마나 따라갔는가(capture)'와 '초과수익이 났는가(excess)'다.
    """
    by_id = {r["id"]: r for r in rows if r.get("status") == "ok"}
    for r in rows:
        if r.get("status") != "ok" or not r.get("bm"):
            continue
        b = by_id.get(r["bm"])
        if not b:
            continue
        r["bm_name"] = b.get("name")
        for h in ("1y", "3y", "si"):
            f, g = r.get(f"tr_{h}"), b.get(f"tr_{h}")
            r[f"excess_{h}"] = round(f - g, 2) if (f is not None and g is not None) else None
        f, g = r.get("tr_1y"), b.get("tr_1y")
        r["capture_1y"] = round(f / g * 100, 1) if (f is not None and g and g > 0) else None
        fm, gm = r.get("mdd_1y"), b.get("mdd_1y")
        r["mdd_edge_1y"] = round(fm - gm, 2) if (fm is not None and gm is not None) else None
    return rows


def score(rows):
    """총수익률 우선 관점의 종합 점수(0~100).

    가중치: 원지수 대비 초과수익 40 / 절대 총수익 15 / 낙폭 방어력 20 / 분배율 15 / 저보수 10
    초과수익을 절대수익보다 크게 잡는 이유는 시장 국면(한국 강세장 등)을 상쇄하기 위함이다.
    """
    def pctile(arr, v, higher_better=True):
        clean = [x for x in arr if x is not None]
        if not clean or v is None:
            return None
        n = len(clean)
        if n == 1:
            return 50.0
        pos = sum(1 for x in clean if (x < v if higher_better else x > v))
        return pos / (n - 1) * 100

    # 점수는 '커버드콜끼리'의 상대평가다. 원지수(BM)·원자재(CM)·레버리지(LV)는
    # 애초에 옵션 매도를 하지 않으므로 같은 자로 재면 순위가 왜곡된다.
    NON_CC = ("BM", "CM", "LV")
    pool = [r for r in rows if r.get("status") == "ok" and r.get("gen") not in NON_CC]
    for r in pool:
        m = r.get("mdd_1y")
        r["calmar_1y"] = (round(r["tr_1y"] / abs(m), 2)
                          if (r.get("tr_1y") is not None and m) else None)

    cols = {k: [r.get(k) for r in pool]
            for k in ("excess_1y", "tr_1y", "mdd_edge_1y", "ttm_yield", "er")}
    W = (("excess_1y", 40, True), ("tr_1y", 15, True), ("mdd_edge_1y", 20, True),
         ("ttm_yield", 15, True), ("er", 10, False))

    for r in pool:
        parts, wts = [], []
        for k, w, hb in W:
            p = pctile(cols[k], r.get(k), hb)
            if p is not None:
                parts.append(p * w)
                wts.append(w)
        r["score"] = round(sum(parts) / sum(wts), 1) if wts else None
    return rows


# ══════════════════════════════════════════════ 실행

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", action="store_true", help="원시 데이터 캐시 재사용")
    ap.add_argument("--only-us", action="store_true")
    ap.add_argument("--only-kr", action="store_true")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    uni = json.load(open(UNIVERSE, encoding="utf-8"))

    cache = {}
    if args.cache and os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
            print(f"[cache] {len(cache)}건 재사용")
        except Exception:
            cache = {}

    rows, errors = [], []
    jobs = []
    if not args.only_kr:
        jobs += [("US", m, "US:" + m["ticker"], fetch_us, compute_us, m["ticker"]) for m in uni["us"]]
    if not args.only_us:
        jobs += [("KR", m, "KR:" + m["code"], fetch_kr, compute_kr, m["code"]) for m in uni["kr"]]

    krdiv = {}
    if os.path.exists(KRDIV):
        try:
            krdiv = json.load(open(KRDIV, encoding="utf-8"))
        except Exception:
            krdiv = {}

    for market, meta, key, fetch, compute, ident in jobs:
        try:
            if key not in cache:
                cache[key] = fetch(ident)
                time.sleep(0.35)
            if market == "KR":
                if ident not in krdiv:
                    krdiv[ident] = fetch_kr_dividends(ident) or []
                    time.sleep(0.2)
                cache[key]["dividends"] = krdiv.get(ident) or []
            rows.append(compute(meta, cache[key]))
            print(f"  OK  {ident:8s} {meta.get('name','')[:38]}")
        except Exception as e:
            errors.append(f"{ident}: {e}")
            rows.append({**meta, "status": "error", "id": ident, "market": market})
            print(f"  ERR {ident:8s} {e}")

    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(krdiv, open(KRDIV, "w", encoding="utf-8"), ensure_ascii=False)
    rows = score(attach_benchmark(rows))
    axis = build_axis(rows)
    fx = cache.get("FX:USDKRW") if args.cache else None
    if not fx:
        fx = fetch_fx()
        if fx:
            cache["FX:USDKRW"] = fx
            json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  FX  USD/KRW = {fx}")

    payload = {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "generations": uni["generations"],
        "axis": axis,
        "fx": {"usdkrw": fx},
        "rows": rows,
        "errors": errors,
    }
    json.dump(payload, open(METRICS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    tpl = open(os.path.join(ROOT, "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null",
                       json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    open(OUT_HTML, "w", encoding="utf-8").write(html)
    open(OUT_INDEX, "w", encoding="utf-8").write(html)

    ok = sum(1 for r in rows if r.get("status") == "ok")
    print(f"\n\uc644\ub8cc: {ok}/{len(rows)} \u2192 {OUT_HTML}")
    if errors:
        print("\uc2e4\ud328:", "; ".join(errors))


if __name__ == "__main__":
    main()
