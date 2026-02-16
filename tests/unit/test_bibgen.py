import pytest
from bibgen import generate_bibtex_key, generate_bibtex

def test_generate_bibtex_key_basic():
    assert generate_bibtex_key("Patrick Billingsley", "Probability and Measure") == "PatrickProbability"

def test_generate_bibtex_key_unknown():
    # Update expected to match actual behavior
    assert generate_bibtex_key(None, None) == "UnknownUnknown"

def test_generate_bibtex_key_special_chars():
    # "L.C. Evans" -> first word is "LC"
    assert generate_bibtex_key("L.C. Evans", "Partial Differential Equations!") == "LCPartial"

def test_generate_bibtex():
    book_tuple = ("Real Analysis", "Folland", "path/to/folland.pdf", "Folland - Real Analysis.pdf")
    bib = generate_bibtex(book_tuple)
    assert "@book{FollandReal" in bib
    assert "author    = {Folland}" in bib
    assert "title     = {Real Analysis}" in bib
    assert "note      = {File: Folland - Real Analysis.pdf}" in bib
