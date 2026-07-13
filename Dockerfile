FROM python:3.12-slim

# LibreOffice (necessario para converter os certificados .docx em .pdf)
# e fontes para o texto renderizar corretamente.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice \
    fonts-crosextra-carlito \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--timeout", "120"]
