from elasticsearch import Elasticsearch
from core.config import ELASTICSEARCH_URL

# Global Elasticsearch Client
# In development, security might be disabled as seen in docker-compose.yml
es_client = Elasticsearch(
    ELASTICSEARCH_URL,
    retry_on_timeout=True,
    max_retries=3
)

def create_mathstudio_indices():
    """Initializes the three core indices in Elasticsearch with strict mappings."""
    
    # 1. mathstudio_books: High-level book metadata and dense embeddings
    books_mapping = {
        "mappings": {
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "text", "analyzer": "english"},
                "author": {"type": "text", "analyzer": "standard"},
                "summary": {"type": "text", "analyzer": "english"},
                "description": {"type": "text", "analyzer": "english"},
                "msc_class": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "zbl_id": {"type": "keyword"},
                "doi": {"type": "keyword"},
                "isbn": {"type": "keyword"},
                "year": {"type": "integer"},
                "publisher": {"type": "keyword"},
                "toc": {"type": "text", "analyzer": "english"},
                "index_text": {"type": "text", "analyzer": "english"},
                "zb_review": {"type": "text", "analyzer": "english"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": 768,
                    "index": True,
                    "similarity": "cosine"
                }
            }
        }
    }

    # 2. mathstudio_pages: Granular page-level content for deep indexing
    pages_mapping = {
        "mappings": {
            "properties": {
                "book_id": {"type": "integer"},
                "page_number": {"type": "integer"},
                "content": {"type": "text", "analyzer": "english"}
            }
        }
    }

    # 3. mathstudio_terms: Knowledge Base terms (Theorems, Definitions, etc.)
    terms_mapping = {
        "mappings": {
            "properties": {
                "id": {"type": "integer"},
                "book_id": {"type": "integer"},
                "concept_id": {"type": "integer"},
                "page_start": {"type": "integer"},
                "name": {"type": "text", "analyzer": "english", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
                "term_type": {"type": "keyword"}, # definition, theorem, lemma, etc.
                "latex_content": {"type": "text"},
                "used_terms": {"type": "keyword"},
                "status": {"type": "keyword"}, # draft, approved
                "embedding": {"type": "dense_vector", "dims": 768}
            }
        }
    }

    # 4. mathstudio_concepts: Canonical Mathematical Concepts
    concepts_mapping = {
        "mappings": {
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "text", "analyzer": "english", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
                "subject_area": {"type": "keyword"},
                "summary": {"type": "text", "analyzer": "english"},
                "embedding": {"type": "dense_vector", "dims": 768}
            }
        }
    }

    indices = {
        "mathstudio_books": books_mapping,
        "mathstudio_pages": pages_mapping,
        "mathstudio_terms": terms_mapping,
        "mathstudio_concepts": concepts_mapping
    }

    for index_name, mapping in indices.items():
        if es_client.indices.exists(index=index_name):
            print(f"Index {index_name} already exists. Skipping.")
        else:
            print(f"Creating index {index_name}...")
            es_client.indices.create(index=index_name, body=mapping)

def index_book(book_data):
    """Indexes a single book into mathstudio_books."""
    try:
        es_client.index(index="mathstudio_books", id=book_data['id'], document=book_data)
        return True
    except Exception as e:
        print(f"[ES] Error indexing book {book_data.get('id')}: {e}")
        return False

def index_page(book_id, page_number, content):
    """Indexes a single page into mathstudio_pages."""
    try:
        doc = {
            "book_id": book_id,
            "page_number": page_number,
            "content": content
        }
        es_client.index(index="mathstudio_pages", document=doc)
        return True
    except Exception as e:
        print(f"[ES] Error indexing page {page_number} for book {book_id}: {e}")
        return False

def index_term(term_data):
    """Indexes a single term into mathstudio_terms."""
    try:
        es_client.index(index="mathstudio_terms", id=term_data['id'], document=term_data)
        return True
    except Exception as e:
        print(f"[ES] Error indexing term {term_data.get('id')}: {e}")
        return False

if __name__ == "__main__":
    create_mathstudio_indices()
