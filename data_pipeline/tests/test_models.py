from magic_formula.models import ScrapedStock, TickerInfo
from magic_formula.parsers.overview import OverviewParser
from magic_formula.parsers.profit_loss import ProfitLossParser
from magic_formula.parsers.quarterly_results import QuarterlyResultsParser
from magic_formula.parsers.ratios import RatiosParser


def _ticker(name: str = "TestCo") -> TickerInfo:
    return TickerInfo(stock_id="TST01", stock_name=name, link_src="https://example.com/tst", raw={"name": name})


def test_record_derives_magic_formula_columns():
    stock = ScrapedStock(
        ticker=_ticker(),
        overview={
            "Mkt Cap (Rs. Cr.)": "1,774,657",
            "Previous Close": "1,311.00",
            "Book Value Per Share": "668.04",
        },
        profit_loss={"Annual EBIT (Cr.)": "150,223"},
        quarter_results={},
        ratios={},
    )

    record = stock.to_record()

    pbit_share = record["PBIT/Share (Rs.)"]
    ev = record["Enterprise Value (Cr.)"]
    roce = record["Return on Capital Employed (%)"]

    assert abs(pbit_share - (150223 * 1311.00) / 1774657) < 1e-9
    assert ev == 1774657
    equity_cr = (668.04 * 1774657) / 1311.00
    assert abs(roce - (150223 / equity_cr) * 100) < 1e-9


def test_record_survives_missing_inputs():
    stock = ScrapedStock(ticker=_ticker(), overview={}, profit_loss={}, quarter_results={}, ratios={})

    record = stock.to_record()

    assert "PBIT/Share (Rs.)" not in record
    assert "Return on Capital Employed (%)" not in record


def test_record_merges_live_parser_output(overview_html, profit_loss_html, ratios_html, quarterly_html):
    stock = ScrapedStock(
        ticker=_ticker("Reliance Industries"),
        overview=OverviewParser().parse(overview_html),
        profit_loss=ProfitLossParser().parse(profit_loss_html),
        quarter_results=QuarterlyResultsParser().parse(quarterly_html),
        ratios=RatiosParser().parse(ratios_html),
    )

    record = stock.to_record()

    required = [
        "Mkt Cap (Rs. Cr.)",
        "Previous Close",
        "Annual EBIT (Cr.)",
        "PBIT/Share (Rs.)",
        "Enterprise Value (Cr.)",
    ]
    for column in required:
        assert column in record and record[column] not in (None, ""), f"missing {column}"
