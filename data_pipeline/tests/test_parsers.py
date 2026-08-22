from magic_formula.parsers.overview import OverviewParser
from magic_formula.parsers.profit_loss import ProfitLossParser
from magic_formula.parsers.ratios import RatiosParser


def _to_float(value) -> float:
    return float(str(value).replace(",", ""))


def test_overview_extracts_headline_metrics(overview_html):
    data = OverviewParser().parse(overview_html)

    assert _to_float(data["Mkt Cap (Rs. Cr.)"]) > 0
    assert _to_float(data["Previous Close"]) > 0
    assert _to_float(data["TTM EPS"]) != 0


def test_profit_loss_extracts_annual_rows(profit_loss_html):
    data = ProfitLossParser().parse(profit_loss_html)

    for key in ["Annual EBIT (Cr.)", "Annual Interest (Cr.)", "Annual Net Profit (Cr.)"]:
        assert key in data, f"missing {key}"
        assert _to_float(data[key]) > 0


def test_ratios_whitelists_structured_fields(ratios_html):
    data = RatiosParser().parse(ratios_html)

    expected_keys = {
        "TTM EPS",
        "Book Value [ExclRevalReserve]/Share (Rs.)",
        "Face Value",
    }
    missing = expected_keys - data.keys()
    assert not missing, f"RatiosParser lost expected fields: {missing}"

    assert _to_float(data["TTM EPS"]) != 0


def test_ratios_never_leaks_peer_names(ratios_html):
    data = RatiosParser().parse(ratios_html)

    banned = {"HDFC Bank", "Reliance Industries", "BSE Sensex", "Nifty"}
    leaked = banned & set(data.keys())
    assert not leaked, f"Peer/index names leaked into ratio keys: {leaked}"
