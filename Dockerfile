FROM python:3.11-slim

WORKDIR /app

# Instalar solo lo esencial (sin gcc innecesario)
RUN apt-get update && apt-get install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements.txt primero (mejor caché de Docker)
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto de la aplicación
COPY . .

# Puerto para Render
ENV PORT=10000

# Iniciar Gunicorn directamente (sin script intermedio)
CMD gunicorn --bind 0.0.0.0:$PORT --workers=1 --threads=4 app:app
