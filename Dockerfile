FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema necesarias para psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements.txt primero (mejor para caché de Docker)
COPY requirements.txt .

# Instalar dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto de la aplicación
COPY . .

# Dar permisos de ejecución al script de inicio
RUN chmod +x start.sh

# Puerto para Render
ENV PORT=10000

# Comando para iniciar la aplicación usando nuestro script
CMD ./start.sh
