# Usamos una versión ligera de Python
FROM python:3.11-slim

# Establecemos el directorio de trabajo
WORKDIR /app

# Copiamos las dependencias y las instalamos
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto de nuestro código
COPY . .

# Exponemos el puerto 8080 (Requisito de GCP Cloud Run)
ENV PORT=8080
EXPOSE 8080

# Comando para arrancar el servidor web de nuestros agentes
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]