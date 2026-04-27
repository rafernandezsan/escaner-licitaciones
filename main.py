import os
import psycopg2
import json
import io
import html
import hashlib
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from google.cloud import storage
from langchain_google_vertexai import ChatVertexAI
from langchain_core.messages import HumanMessage
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

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


import google.auth
from google.auth import impersonated_credentials
from google.cloud import storage
from datetime import timedelta

@app.post("/generar_descarga")
async def generar_descarga(id_doc: int = Form(...)):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT documento_url FROM documentos_licitacion WHERE id = %s", (id_doc,))
    res = cur.fetchone()
    
    if not res:
        return {"error": "No encontrado"}, 404
        
    gcs_uri = res[0]
    
    # --- LA MAGIA DE LA IMPERSONACIÓN (IAM Signer) ---
    service_account_email = "1066450737358-compute@developer.gserviceaccount.com"
    
    # 1. Obtener las credenciales base (tokens) de Cloud Run
    default_creds, project_id = google.auth.default()
    
    # 2. Envolverlas en "Credenciales Impersonadas"
    # Este objeto SÍ tiene el método sign_bytes() que la librería exige,
    # y usa la API de IAM internamente para firmar.
    iam_creds = impersonated_credentials.Credentials(
        source_credentials=default_creds,
        target_principal=service_account_email,
        target_scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    
    # 3. Inicializar el cliente Storage con la envoltura
    client = storage.Client(credentials=iam_creds, project=project_id)
    bucket = client.bucket(BUCKET_NAME)
    blob_path = gcs_uri.replace(f"gs://{BUCKET_NAME}/", "")
    blob = bucket.blob(blob_path)
    
    # 4. Generar URL (ya no necesitamos pasar el service_account_email aquí)
    url_firmada = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=15),
        method="GET"
    )
    
    cur.close()
    conn.close()
    return {"url_descarga": url_firmada}


# --- ENDPOINT 3: GENERACIÓN DE REPORTE PDF ---
@app.post("/generar_reporte_pdf")
async def generar_reporte_pdf(id_proceso: str = Form(...)):
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT titulo, estado, puntuacion, reporte_completo 
        FROM analisis_licitaciones 
        WHERE id_proceso = %s
    """, (id_proceso,))
    res = cur.fetchone()
    
    cur.close()
    conn.close()
    
    if not res:
        raise HTTPException(status_code=404, detail="Licitación no encontrada")
        
    titulo, estado, puntuacion, reporte_completo = res
    reporte_completo = reporte_completo if reporte_completo else "No hay análisis de IA disponible aún."
    puntuacion = puntuacion if puntuacion else 0
    
    # 1. Crear el PDF en memoria usando un buffer
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # 2. Ensamblar la estructura del documento
    story.append(Paragraph(f"Reporte Ejecutivo: {id_proceso}", styles['Title']))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>Título de la Licitación:</b> {html.escape(titulo if titulo else 'N/A')}", styles['Normal']))
    story.append(Paragraph(f"<b>Estado del Expediente:</b> {html.escape(estado if estado else 'N/A')}", styles['Normal']))
    story.append(Paragraph(f"<b>Puntuación Asignada por IA:</b> {puntuacion}/10", styles['Normal']))
    story.append(Spacer(1, 24))
    
    story.append(Paragraph("<b>Razonamiento y Análisis de Gemini:</b>", styles['Heading2']))
    
    # 3. Formatear el reporte de la IA (manejamos saltos de línea básicos)
    for parrafo in reporte_completo.split('\n'):
        if parrafo.strip():
            # Escapamos los signos &, < y > para evitar errores en el parseo XML interno de ReportLab
            texto_seguro = html.escape(parrafo.strip())
            story.append(Paragraph(texto_seguro, styles['Normal']))
            story.append(Spacer(1, 6))
            
    doc.build(story)
    
    # 4. Preparar el buffer para lectura
    buffer.seek(0)
    
    # 5. Retornar el archivo PDF generado
    return StreamingResponse(
        buffer, 
        media_type="application/pdf", 
        headers={"Content-Disposition": f'attachment; filename="Reporte_Licitacion_{id_proceso}.pdf"'}
    )

# --- ENDPOINT 4: CREACIÓN DE USUARIOS (SIGNUP) ---
@app.post("/signup")
async def create_user(
    email: str = Form(...),
    password: str = Form(...),
    rol: str = Form(default="analista"), # Roles esperados: administrador, analista, invitado
    admin_email: str = Form(...),
    admin_password: str = Form(...)
):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Asegurar que la tabla existe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY, 
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL, 
            rol VARCHAR(50) NOT NULL
        )
    """)
    conn.commit()
    
    # 2. Validar que quien hace la petición es un administrador válido
    is_admin = False
    if admin_email == os.environ.get("ADMIN_EMAIL") and admin_password == os.environ.get("ADMIN_PASSWORD"):
        is_admin = True
    else:
        admin_hash = hashlib.sha256(admin_password.encode()).hexdigest()
        cur.execute("SELECT id FROM usuarios WHERE email = %s AND password_hash = %s AND rol = 'administrador'", (admin_email, admin_hash))
        if cur.fetchone():
            is_admin = True
            
    if not is_admin:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="No autorizado. Solo un administrador puede crear nuevos usuarios.")
        
    # 3. Insertar el nuevo usuario en la base de datos
    hashed_pw = hashlib.sha256(password.encode()).hexdigest()
    try:
        cur.execute("INSERT INTO usuarios (email, password_hash, rol) VALUES (%s, %s, %s)", (email, hashed_pw, rol))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="El correo electrónico ya está registrado.")
    finally:
        cur.close()
        conn.close()
        
    return {"status": "success", "message": f"Usuario {email} creado exitosamente con el rol '{rol}'."}