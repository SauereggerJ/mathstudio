# Basis-Image: Schlankes Python 3.11
FROM python:3.11-slim

# System-Tools installieren (wichtig für DJVU & Bilder & PDFLaTeX)
RUN apt-get update && apt-get install -y \
    djvulibre-bin \
    netpbm \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-extra \
    texlive-science \
    && rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis im Container
WORKDIR /app

# Python-Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Den gesamten Code kopieren
COPY . .

# Port freigeben
EXPOSE 5001

# Startbefehl
CMD ["python", "app.py"]
