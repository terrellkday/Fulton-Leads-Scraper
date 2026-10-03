"""Regression tests for the 2026-10-02 Claude-review fixes.

Run:  python3 scraper/test_regression.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch import (  # noqa: E402
    _qpublic_key,
    _split_city_state_zip,
    _strip_notice_header,
    _tax_pdf_rank,
    _looks_like_tax_listing,
    _rank_tax_pdfs,
    build_flags,
    categorize,
    parse_money,
    sha_key,
    split_person_name,
    PARCEL_ID_IN_TEXT_RE,
    LegalNoticeScraper,
)


def test_zip_plus4_with_space():
    # The qPublic mailing line "ELLENWOOD GA 30294 2213" used to come back
    # with the whole line as the city and empty state/ZIP.
    assert _split_city_state_zip("ELLENWOOD GA 30294 2213") == (
        "", "Ellenwood", "GA", "30294-2213")
    # Hyphenated form keeps working and keeps the +4.
    assert _split_city_state_zip("ELLENWOOD GA 30294-2213") == (
        "", "Ellenwood", "GA", "30294-2213")
    # Plain ZIP untouched.
    assert _split_city_state_zip("ELLENWOOD GA 30294") == (
        "", "Ellenwood", "GA", "30294")


def test_notice_id_from_ad_code():
    body = ("CND7862 GPN11 NOTICE OF FORECLOSURE OF RIGHT TO REDEEM REAL "
            "PROPERTY FROM TAX SALE. County: Fulton. TO: Marcia Davis and "
            "Kitoshia Eason. Pursuant to O.C.G.A. 48-4-45, the property will "
            "be sold at public outcry before the courthouse door to the "
            "highest bidder for cash. This is a legal advertisement.")
    html = (f"<html><body><div class='results'><div class='ad'>"
            f"<div class='adbody'>{body}</div></div></div></body></html>")
    assert len(body) > 150
    out = LegalNoticeScraper._parse_results(html, "TAX")
    # Nested divs must not double-emit: one ad, one record.
    assert len(out) == 1, f"expected 1 record, got {len(out)}"
    # The leading alphanumeric ad code is the stable id, not a content hash
    # (fixture code kept from the Clayton-era regression suite).
    assert out[0]["notice_id"] == "CND7862", out[0]["notice_id"]


def test_notice_hash_stable_across_republication():
    t1 = ("NOTICE OF SALE UNDER POWER Wednesday, October 1, 2025 "
          "County: Fulton body body body")
    t2 = ("NOTICE OF SALE UNDER POWER Wednesday, October 8, 2025 "
          "County: Fulton body body body")
    assert sha_key(_strip_notice_header(t1)) == sha_key(_strip_notice_header(t2))
    # ...but genuinely different notices still hash differently.
    t3 = ("NOTICE OF SALE UNDER POWER Wednesday, October 8, 2025 "
          "County: Fulton different body here")
    assert sha_key(_strip_notice_header(t1)) != sha_key(_strip_notice_header(t3))


def test_split_person_name_orders():
    # Legal notices use natural order.
    assert split_person_name("Marcia Davis and Kitoshia Eason", "natural") == (
        "Marcia", "Davis")
    assert split_person_name("OLGA MARIA VEGA", "natural") == (
        "Olga Maria", "Vega")
    # Joint owners on &: first person only.
    assert split_person_name("DAVIS MARCIA & EASON KITOSHIA", "last-first") == (
        "Marcia", "Davis")
    # Deed-index order is the default.
    assert split_person_name("THOMAS IZOIA P") == ("Izoia P", "Thomas")
    assert split_person_name("SMITH JOHN", "last-first") == ("John", "Smith")


def test_tax_pdf_rank_two_digit_year():
    assert _tax_pdf_rank("NOVEMBER TAX SALE LISTING 9-8-26.pdf")[:2] == (2026, 11)
    assert _tax_pdf_rank("10-6-26.pdf")[:2] == (2026, 10)
    assert _tax_pdf_rank("september_2026_tax_sale.pdf")[:2] == (2026, 9)


def test_tax_listing_name_filter():
    assert _looks_like_tax_listing("september_2026_tax_sale.pdf")
    assert _looks_like_tax_listing("NOVEMBER TAX SALE LISTING 9-8-26.pdf")
    assert _looks_like_tax_listing("TAX SALE LISTING-APRIL 2026-1.pdf")
    assert not _looks_like_tax_listing("DQ759GA.pdf")
    assert not _looks_like_tax_listing("DQ759GA_20250204.pdf")
    assert not _looks_like_tax_listing("budget_2027.pdf")
    assert not _looks_like_tax_listing("Tax_Real_Property_Return.pdf")
    assert not _looks_like_tax_listing("OfficialClaimforExcessFund.pdf")


def test_tax_pdf_rank_prefers_listing_date():
    links = [
        ("september_2026_tax_sale.pdf", "u1", "2026-08-06"),
        ("NOVEMBER TAX SALE LISTING 9-8-26.pdf", "u2", "2026-09-09"),
        ("DQ759GA.pdf", "u3", "2026-09-10"),
    ]
    ranked = _rank_tax_pdfs(links)
    assert [n for n, _ in ranked] == [
        "NOVEMBER TAX SALE LISTING 9-8-26.pdf",
        "september_2026_tax_sale.pdf",
    ]


def test_past_tax_sale_flag():
    start = datetime.now() - timedelta(days=3)
    end = datetime.now()
    past = {"cat": "TAX", "tax_sale_date": "2026-09-01", "owner": "X"}
    flags = build_flags(past, {"categories": set()}, start, end)
    assert "Past tax sale / redemption period" in flags, flags
    assert "Tax sale" not in flags, flags
    future = {"cat": "TAX", "tax_sale_date": "2026-11-03", "owner": "X"}
    flags2 = build_flags(future, {"categories": set()}, start, end)
    assert "Tax sale" in flags2, flags2
    assert "Past tax sale / redemption period" not in flags2, flags2


def test_parse_money_fallback_capped():
    # A huge digit run with no $ sign is not a $100B debt.
    assert parse_money("ref 99999999999x") is None
    assert parse_money("$12,196.37") == 12196.37


def test_categorize_word_boundary():
    assert categorize("TAX SALE")[0] == "TAX"
    # "ESTATE" must not match inside a longer word.
    assert categorize("REALESTATE HOLDINGS")[0] == "UNK"


def test_split_city_state_zip_comma():
    # The template county's qPublic renders "NEWNAN, GA 30265" -- the comma
    # must not end up in the city name.
    assert _split_city_state_zip("NEWNAN, GA 30265") == (
        "", "Newnan", "GA", "30265")
    assert _split_city_state_zip("SHARPSBURG, GA 30277") == (
        "", "Sharpsburg", "GA", "30277")


def test_parcel_id_coweta_formats():
    # The template county's alphanumeric parcels plus the Clayton-era
    # numeric pattern -- kept as a regression.
    assert PARCEL_ID_IN_TEXT_RE.search("parcel W09 030 here").group(1) == "W09 030"
    assert PARCEL_ID_IN_TEXT_RE.search("parcel 111 1019 052 here").group(1) == "111 1019 052"
    assert PARCEL_ID_IN_TEXT_RE.search("parcel 05 079 02 003 here").group(1) == "05 079 02 003"


def test_parcel_id_fulton_formats():
    # Fulton's real formats, captured 2026-10-02 from live qPublic reports:
    # "17 013200020458" and the land-lot form "17 0162 LL0082".
    assert PARCEL_ID_IN_TEXT_RE.search("parcel 17 013200020458 here").group(1) == "17 013200020458"
    assert PARCEL_ID_IN_TEXT_RE.search("parcel 17 0162 LL0082 here").group(1) == "17 0162 LL0082"
    assert PARCEL_ID_IN_TEXT_RE.search("parcel 14 024300030682 here").group(1) == "14 024300030682"
    assert PARCEL_ID_IN_TEXT_RE.search("parcel 07 070101090296 here").group(1) == "07 070101090296"


def test_qpublic_key_preserves_spacing():
    # Each whitespace char becomes one '+'; nothing is collapsed.
    assert _qpublic_key("W09 030") == "W09+030"
    assert _qpublic_key("111 1019 052") == "111+1019+052"


if __name__ == "__main__":
    test_zip_plus4_with_space()
    test_notice_id_from_ad_code()
    test_notice_hash_stable_across_republication()
    test_split_person_name_orders()
    test_tax_pdf_rank_two_digit_year()
    test_tax_listing_name_filter()
    test_tax_pdf_rank_prefers_listing_date()
    test_past_tax_sale_flag()
    test_parse_money_fallback_capped()
    test_categorize_word_boundary()
    test_split_city_state_zip_comma()
    test_parcel_id_coweta_formats()
    test_parcel_id_fulton_formats()
    test_qpublic_key_preserves_spacing()
    print("ALL REGRESSION TESTS PASSED")
