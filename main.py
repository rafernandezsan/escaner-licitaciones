import os
import base64
import psycopg2
from fastapi import FastAPI, UploadFile, File, Form
from google.cloud import storage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

app = FastAPI()
BUCKET_NAME = "escaner-licitaciones-docs-escanerlicitaciones"

def get_db_connection():
    return psycopg2.connect(host=os.environ["DB_HOST"], database=os.environ["DB_NAME"], 
                            user=os.environ["DB_USER"], password=os.environ["DB_PASS"])

def upload_to_gcs(file_bytes, file_name):
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(file_name)
    blob.upload_from_string(file_bytes, content_type='application/pdf')
    return f"gs://{BUCKET_NAME}/{file_name}"

def download_from_gcs(gcs_uri):
    """Descarga el archivo de GCS a la memoria de Cloud Run para enviarlo a Gemini"""
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob_name = gcs_uri.split(f"gs://{BUCKET_NAME}/")[-1]
    blob = bucket.blob(blob_name)
    return blob.download_as_bytes()

@app.post("/")
async def analizar_o_reevaluar(
    id_proceso: str = Form(...),
    titulo: str = Form(None),
    archivo: UploadFile = File(None)
):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Obtener el Documento y los Bytes
    gcs_uri = None
    file_bytes = None
    
    if archivo:
        file_bytes = await archivo.read()
        gcs_uri = upload_to_gcs(file_bytes, f"{id_proceso}.pdf")
    else:
        cur.execute("SELECT documento_url FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
        res = cur.fetchone()
        if res and res[0]: 
            gcs_uri = res[0]
            # Si es re-evaluación, bajamos el archivo de la nube a la memoria
            file_bytes = download_from_gcs(gcs_uri)

    # 2. Obtener Memoria (Notas)
    cur.execute("SELECT notas FROM analisis_licitaciones WHERE id_proceso = %s", (id_proceso,))
    memoria = cur.fetchone()
    notas = memoria[0] if memoria and memoria[0] else "Sin notas adicionales."
    
    # 3. Razonamiento de Gemini (Usando ChatGoogleGenerativeAI)
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0)
    
    instruccion = f"""Analiza esta licitación técnica. 
    CONTEXTO DEL CONSULTOR: {notas}
    Si hay notas, ajusta el score basándote en ellas. 
    Responde estrictamente en JSON: {{"puntuacion": 8, "razonamiento": "explicación", "es_objetivo": true}}"""
    
    # Preparamos el contenido
    contenido_mensaje = [{"type": "text", "text": instruccion}]
    
    # Si logramos conseguir el PDF, lo codificamos en Base64 y lo adjuntamos
    if file_bytes:
        pdf_b64 = base64.b64encode(file_bytes).decode("utf-8")
        contenido_mensaje.append({
            "type": "image_url", 
            "image_url": {"url": f"data:application/pdf;base64,{pdf_b64}"}
        })
    else:
        contenido_mensaje[0]["text"] += "\n[ADVERTENCIA: No se encontró ningún documento PDF vinculado para analizar.]"

    mensaje = HumanMessage(content=contenido_mensaje)
    resultado = llm.invoke([mensaje])
    
    # Extraemos el JSON
    import json
    texto_ia = resultado.content.replace('```json', '').replace('```', '').strip()
    try:
        data_ia = json.loads(texto_ia)
    except:
        data_ia = {"puntuacion": 0, "razonamiento": "Error al procesar la respuesta de la IA.", "es_objetivo": False}

    # 4. Sincronizar Base de Datos
    cur.execute("""
        INSERT INTO analisis_licitaciones (id_proceso, titulo, documento_url, puntuacion, es_objetivo, reporte_completo, estado)
        VALUES (%s, %s, %s, %s, %s, %s, 'Analizada')
        ON CONFLICT (id_proceso) DO UPDATE SET 
            puntuacion = EXCLUDED.puntuacion,
            reporte_completo = EXCLUDED.reporte_completo,
            documento_url = COALESCE(EXCLUDED.documento_url, analisis_licitaciones.documento_url)
    """, (id_proceso, titulo, gcs_uri, data_ia['puntuacion'], data_ia['es_objetivo'], data_ia['razonamiento']))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "score": data_ia['puntuacion']}