import pytest
from services.metadata import metadata_service

def test_generate_bibtex_key_basic():
    assert metadata_service.generate_bibtex_key("Patrick Billingsley", "Probability and Measure") == "PatrickProbability"

def test_generate_bibtex_key_unknown():
    assert metadata_service.generate_bibtex_key(None, None) == "UnknownUnknown"

def test_generate_bibtex_key_special_chars():
    assert metadata_service.generate_bibtex_key("L.C. Evans", "Partial Differential Equations!") == "LCPartial"

def test_generate_bibtex():
    bib = metadata_service.generate_bibtex("Real Analysis", "Folland", "Folland - Real Analysis.pdf")
    assert "@book{FollandReal" in bib
    assert "author    = {Folland}" in bib
    assert "title     = {Real Analysis}" in bib
    assert "note      = {File: Folland - Real Analysis.pdf}" in bib
