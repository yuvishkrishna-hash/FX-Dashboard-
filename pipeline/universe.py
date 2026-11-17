"""The 28 major and minor FX pairs. No exotics."""

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    "NZDJPY", "NZDCHF", "NZDCAD",
    "CADJPY", "CADCHF", "CHFJPY",
]

N_PAIRS = len(PAIRS)
N_RETURNS = 250
EST_N = 500
NEED_N = EST_N + N_RETURNS  # 750 closes: 500 to estimate, 250 to evaluate
CORR_N = 504
TOP_PER_SECTOR = 20
LOOKBACK_DAYS = 1400
PRICE_LOOKBACK_DAYS = 1700
SAST_NAME = "Africa/Johannesburg"

# Y / X. Natural gas (NG=F) is left out: contract-roll jumps dominate the spread.
COMMODITY_PAIRS = [
    {"id": "si-gc", "y": "SI=F", "x": "GC=F", "yName": "Silver", "xName": "Gold"},
    {"id": "bz-cl", "y": "BZ=F", "x": "CL=F", "yName": "Brent", "xName": "WTI"},
    {"id": "pl-gc", "y": "PL=F", "x": "GC=F", "yName": "Platinum", "xName": "Gold"},
    {"id": "gdx-gc", "y": "GDX", "x": "GC=F", "yName": "Gold miners", "xName": "Gold"},
    {"id": "hg-si", "y": "HG=F", "x": "SI=F", "yName": "Copper", "xName": "Silver"},
    {"id": "aud-gc", "y": "AUDUSD=X", "x": "GC=F", "yName": "AUDUSD", "xName": "Gold"},
    {"id": "cad-cl", "y": "CAD=X", "x": "CL=F", "yName": "USDCAD", "xName": "WTI"},
]

GICS_SECTORS = [
    "Energy",
    "Materials",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Health Care",
    "Financials",
    "Information Technology",
    "Communication Services",
    "Utilities",
    "Real Estate",
]
