# Contexto del Proyecto: Radar Inteligente de Licitaciones DGCP

## 1. Arquitectura Actual
* **Frontend:** Streamlit (`dashboard.py`). Interfaz de usuario que corre localmente y se comunica vía API REST.
* **Backend:** FastAPI (`main.py`) desplegado en Google Cloud Run (Serverless).
* **Base de Datos:** PostgreSQL en Google Cloud SQL (Instancia: `licitaciones-db-instance`).
* **Almacenamiento de Archivos:** Google Cloud Storage (Bucket: `escaner-licitaciones-docs-escanerlicitaciones`).
* **Inteligencia Artificial:** Vertex AI usando el modelo `gemini-2.5-flash` (Multimodal).

## 2. Flujos Completados y Funcionando
* **Repositorio Multidocumento:** El usuario puede subir múltiples archivos (PDF, JPG, TXT) por cada licitación a un bucket privado de GCS.
* **Persistencia:** La base de datos guarda la relación `id_proceso` -> múltiples documentos (con su `mime_type` y `documento_url`).
* **Análisis Integral:** Un endpoint (`/analizar`) toma TODOS los archivos de GCS vinculados a una licitación, junto con las notas del consultor, y los envía a Gemini 2.5 Flash para un análisis cruzado.
* **Seguridad (Descarga y Borrado):** Los archivos son privados. El backend usa *Impersonated Credentials* (IAM Signer) para generar **Signed URLs** de 15 minutos para descargas seguras. También existe un flujo para borrar archivos tanto de GCS como de SQL.

## 3. Próximos Pasos (Pendientes de Desarrollar)
1. **Generación de Reportes PDF:** Crear una función que tome el JSON de respuesta de Gemini (`puntuacion`, `razonamiento`) y genere un documento PDF ejecutivo descargable desde el Dashboard.
2. **Automatización (Web Scraping):** Un script que revise automáticamente el portal de la DGCP para registrar nuevos `id_proceso` y títulos en la base de datos sin ingresarlos manualmente.
3. **Despliegue del Frontend:** Empaquetar `dashboard.py` en un contenedor Docker y desplegarlo en un segundo servicio de Cloud Run para que sea accesible vía web pública.