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

@app.post("/")
async def analizar_multimodal(
    id_proceso: str = Form(...),
    titulo: str = Form(None),
    archivo: UploadFile = File(None)
):
    conn = get_db_connection()
    cur = conn.cursor()
    
    gcs_uri = None
    mime_type = None
    
    # 1. Gestión de Archivos (Subida nueva o recuperación de DB)
    if archivo:
        mime_type = archivo.content_type 
        file_bytes = await archivo.read()
        # Guardamos con el nombre original para mantener la extensión
        gcs_uri = upload_to_gcs(file_bytes, f"{id_proceso}_{archivo.filename}", mime_type)
    else:
        cur.execute("SELECT documento_url, mime_type FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
        res = cur.fetchone()
        if res:
            gcs_uri, mime_type = res[0], res[1]

    # 2. Obtener Notas/Contexto
    cur.execute("SELECT notas FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
    memoria = cur.fetchone()
    notas = memoria[0] if memoria and memoria[0] else "Sin notas adicionales."
    
    # 3. Inteligencia Artificial Multimodal
    llm = ChatVertexAI(model_name="gemini-2.5-flash", location="us-east1", temperature=0)
    
    instruccion = f"""Analiza este documento de licitación o anexo técnico.
    CONTEXTO DEL CONSULTOR: {notas}
    Tarea: Evalúa si es una oportunidad viable.
    Responde estrictamente en formato JSON: {{"puntuacion": 8, "razonamiento": "tu análisis aquí", "es_objetivo": true}}"""
    
    contenido_mensaje = [{"type": "text", "text": instruccion}]
    
    if gcs_uri and mime_type:
        contenido_mensaje.append({
            "type": "media", 
            "file_uri": gcs_uri, 
            "mime_type": mime_type 
        })

    mensaje = HumanMessage(content=contenido_mensaje)
    resultado = llm.invoke([mensaje])
    
    # Limpieza de respuesta JSON
    texto_ia = resultado.content.replace('```json', '').replace('```', '').strip()
    try:
        data_ia = json.loads(texto_ia)
    except:
        data_ia = {"puntuacion": 0, "razonamiento": "Error interpretando la respuesta multimodal.", "es_objetivo": False}

    # 4. Persistencia en Base de Datos
    cur.execute("""
        INSERT INTO analisis_licitaciones (id_proceso, titulo, documento_url, mime_type, puntuacion, es_objetivo, reporte_completo, estado)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'Analizada')
        ON CONFLICT (id_proceso) DO UPDATE SET 
            puntuacion = EXCLUDED.puntuacion,
            reporte_completo = EXCLUDED.reporte_completo,
            documento_url = COALESCE(EXCLUDED.documento_url, analisis_licitaciones.documento_url),
            mime_type = COALESCE(EXCLUDED.mime_type, analisis_licitaciones.mime_type)
    """, (id_proceso, titulo, gcs_uri, mime_type, data_ia['puntuacion'], data_ia['es_objetivo'], data_ia['razonamiento']))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "mime_detectado": mime_type}