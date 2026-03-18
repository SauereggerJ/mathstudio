---
description: Perform a health check of the MathStudio library (sync/pipeline status)
---
### 1. Run the system check script
// turbo
`python3 scripts/system_check.py`

### 2. Analyze the report
The script will output:
- **Synchronization Status**: Checks if terms in SQLite match those linked to concepts and those in Elasticsearch (with embeddings).
- **Pipeline Activity**: Shows if the scan worker is idle, running, or has queued items.
- **Recommendations**: Provides specific manual recovery commands if any discrepancies are found.
