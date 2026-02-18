import pytest
from services.search import search_service

def test_extract_index_pages_basic():
    index_text = "Hausdorff space 12, 14-16, 20"
    assert search_service.extract_index_pages(index_text, "Hausdorff space") == "12, 14-16, 20"

def test_extract_index_pages_with_noise():
    index_text = """Compactness, sequential 45
Compactness, local 48, 50"""
    assert search_service.extract_index_pages(index_text, "Compactness, local") == "48, 50"

def test_extract_index_pages_case_insensitive():
    index_text = "Metric space 100"
    assert search_service.extract_index_pages(index_text, "metric space") == "100"

def test_extract_index_pages_not_found():
    index_text = "Metric space 100"
    assert search_service.extract_index_pages(index_text, "Banach space") is None

def test_extract_index_pages_multi_line():
    index_text = """Lebesgue integral
   definition of, 150
   properties of, 152-155"""
    assert search_service.extract_index_pages(index_text, "Lebesgue integral") == "150, 152-155"

def test_extract_index_pages_hyphen_variation():
    index_text = "p-series 10"
    assert search_service.extract_index_pages(index_text, "p series") == "10"
    
    index_text = "p series 20"
    assert search_service.extract_index_pages(index_text, "p-series") == "20"
