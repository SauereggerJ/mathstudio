#!/bin/bash

# Batch Wikipedia Glossary Scraper for MathStudio

# Linear Algebra
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_linear_algebra" --subject "Linear Algebra" --msc "15"
sleep 20

# Group Theory
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_group_theory" --subject "Group Theory" --msc "20"
sleep 20    

# Complex & Real Analysis (Covers Harmonic)
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_real_and_complex_analysis" --subject "Analysis" --msc "30"
sleep 20

# Representation Theory
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_representation_theory" --subject "Representation Theory" --msc "22"
sleep 20

# Lie Groups & Algebras (Lie Theory)
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_Lie_groups_and_Lie_algebras" --subject "Lie Theory" --msc "22"
sleep 20

# Functional Analysis (Covers Operator & Spectral Theory)
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_functional_analysis" --subject "Functional Analysis" --msc "46"
sleep 20

# Differential / Metric Geometry (Covers Manifolds)
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_differential_geometry_and_topology" --subject "Differential Geometry" --msc "53"
sleep 20

# Algebraic Topology
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_algebraic_topology" --subject "Algebraic Topology" --msc "55"
sleep 20

# Algebraic Geometry
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_algebraic_geometry" --subject "Algebraic Geometry" --msc "14"
sleep 20

# Calculus (Covers ODEs/PDEs)
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_calculus" --subject "Calculus & Differential Equations" --msc "34"
sleep 20

# Ring and Commutative Algebra (Covers Abstract Algebra)
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_ring_theory" --subject "Ring Theory" --msc "16"
sleep 20
.venv/bin/python scripts/ingest_wikipedia.py --url "https://en.wikipedia.org/wiki/Glossary_of_commutative_algebra" --subject "Commutative Algebra" --msc "13"

echo "Batch Glossaries Ingestion Complete!"
