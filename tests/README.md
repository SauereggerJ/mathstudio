# MathStudio Test Suite

This directory contains the automated test suite for MathStudio.

## Structure
*   `unit/`: Tests for individual functions and classes in isolation.
*   `integration/`: Tests for interactions between components (e.g., Search logic + Database).
*   `api/`: Functional tests for the Flask REST API endpoints.

## Strategy
1.  **Isolated Testing**: Core utilities and regex-based extraction are tested with specific edge cases.
2.  **Mocked AI**: All calls to the Gemini API (`google.genai`) are mocked to ensure tests are fast, deterministic, and cost-free.
3.  **Temporary Database**: Tests use a temporary SQLite database initialized with the production schema to ensure query compatibility.
4.  **Fixture-based Setup**: Common resources (like the database and mock client) are managed via `conftest.py`.

## Running Tests
Ensure you are in the project root and have the virtual environment activated:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=.

# Run specific category
pytest tests/unit/
```

## Adding Tests
- Use **Unit Tests** for any new utility function.
- Use **Integration Tests** when changing how components talk to each other.
- Use **API Tests** when adding or modifying REST endpoints.
- Always mock external network calls.
