import os
import psycopg2
import json
from fastapi import FastAPI, UploadFile, File, Form
from google.cloud import storage
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage

app = FastAPI()
BUCKET_NAME = "escaner-licitaciones-docs-escanerlicitaciones"

def get_db_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"], 
        database=os.environ["DB_NAME"], 
        user=os.environ["DB_USER"], 
        password=os.environ["DB_PASS"]
    )

def upload_to_gcs(file_bytes, file_name, content_type):
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(file_name)
    blob.upload_from_string(file_bytes, content_type=content_type)
    return f"gs://{BUCKET_NAME}/{file_name}"

# --- ENDPOINT 1: SOLO ALMACENAMIENTO ---
@app.post("/subir_documento")
async def guardar_en_repositorio(
    id_proceso: str = Form(...),
    archivo: UploadFile = File(...)
):
    mime_type = archivo.content_type
    file_bytes = await archivo.read()
    
    # Guardamos en una subcarpeta por id_proceso para mantener orden
    gcs_uri = upload_to_gcs(file_bytes, f"{id_proceso}/{archivo.filename}", mime_type)
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO documentos_licitacion (id_proceso, documento_url, mime_type, nombre_archivo)
        VALUES (%s, %s, %s, %s)
    """, (id_proceso, gcs_uri, mime_type, archivo.filename))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "message": f"Archivo {archivo.filename} guardado"}

# --- ENDPOINT 2: ANÁLISIS INTEGRAL (EL AGENTE) ---
@app.post("/analizar")
async def analizar_con_todo_el_repositorio(id_proceso: str = Form(...)):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Recuperar todos los documentos vinculados
    cur.execute("SELECT documento_url, mime_type FROM documentos_licitacion WHERE id_proceso = %s", (id_proceso,))
    documentos = cur.fetchall()
    
    # 2. Recuperar notas del consultor
    cur.execute("SELECT notas, titulo FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
    res_licitacion = cur.fetchone()
    notas = res_licitacion[0] if res_licitacion[0] else "Sin notas adicionales."
    titulo = res_licitacion[1]
    
    # 3. Configurar Gemini (Vertex AI)
    llm = ChatVertexAI(model_name="gemini-2.5-flash", location="us-east1", temperature=0)
    
    instruccion = f"""Analiza esta licitación técnica considerando TODOS los documentos adjuntos.
    NOTAS DEL CONSULTOR: {notas}
    Tarea: Evalúa la viabilidad técnica y financiera.
    Responde estrictamente en JSON: {{"puntuacion": 8, "razonamiento": "análisis cruzado...", "es_objetivo": true}}"""
    
    contenido_mensaje = [{"type": "text", "text": instruccion}]
    
    # Inyectamos TODOS los archivos en el mismo contexto
    for doc_url, m_type in documentos:
        contenido_mensaje.append({
            "type": "media", 
            "file_uri": doc_url, 
            "mime_type": m_type 
        })

    resultado = llm.invoke([HumanMessage(content=contenido_mensaje)])
    
    # Procesar respuesta
    texto_ia = resultado.content.replace('```json', '').replace('```', '').strip()
    data_ia = json.loads(texto_ia)

    # 4. Actualizar tabla principal con el resultado del análisis global
    cur.execute("""
        UPDATE analisis_licitaciones SET 
            puntuacion = %s,
            reporte_completo = %s,
            es_objetivo = %s,
            estado = 'Analizada'
        WHERE id_proceso = %s
    """, (data_ia['puntuacion'], data_ia['razonamiento'], data_ia['es_objetivo'], id_proceso))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "puntuacion": data_ia['puntuacion']}

@app.post("/eliminar_documento")
async def eliminar_documento(id_doc: int = Form(...)):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Obtener URL para borrar de GCS
    cur.execute("SELECT documento_url FROM documentos_licitacion WHERE id = %s", (id_doc,))
    res = cur.fetchone()
    
    if res:
        gcs_uri = res[0] # gs://bucket-name/id_proceso/archivo.pdf
        # Lógica para borrar de GCS
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob_path = gcs_uri.replace(f"gs://{BUCKET_NAME}/", "")
        blob = bucket.blob(blob_path)
        blob.delete()
        
        # 2. Borrar de SQL
        cur.execute("DELETE FROM documentos_licitacion WHERE id = %s", (id_doc,))
        conn.commit()
    
    cur.close()
    conn.close()
    return {"status": "success"}


from datetime import timedelta

@app.post("/generar_descarga")
async def generar_descarga(id_doc: int = Form(...)):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Buscar la URL original en la BD
    cur.execute("SELECT documento_url FROM documentos_licitacion WHERE id = %s", (id_doc,))
    res = cur.fetchone()
    
    if not res:
        return {"error": "Documento no encontrado"}, 404
        
    gcs_uri = res[0] # gs://bucket-name/id/archivo.pdf
    
    # 2. Generar URL Firmada de GCS
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob_path = gcs_uri.replace(f"gs://{BUCKET_NAME}/", "")
    blob = bucket.blob(blob_path)
    
    # El enlace expirará en 15 minutos
    url_firmada = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=15),
        method="GET"
    )
    
    cur.close()
    conn.close()
    return {"url_descarga": url_firmada}