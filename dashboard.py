import streamlit as st
import pandas as pd
import requests
import psycopg2

# Configuración de la página
st.set_page_config(page_title="Escaner de Licitaciones", page_icon="🤖", layout="wide")
API_URL = "https://langgraph-orchestrator-worker-1066450737358.us-east1.run.app" # <-- Reemplaza por tu URL real

st.title("🤖 Analizador de Licitaciones AI")

# --- 1. CONEXIÓN A LA BASE DE DATOS ---
@st.cache_data(ttl=5)
def obtener_licitaciones():
    try:
        conn = psycopg2.connect(
            host=st.secrets["DB_HOST"], database=st.secrets["DB_NAME"],
            user=st.secrets["DB_USER"], password=st.secrets["DB_PASS"]
        )
        cursor = conn.cursor()
        # Traemos todas las columnas, incluyendo el documento_url
        cursor.execute("SELECT id_proceso, titulo, estado, puntuacion, notas, reporte_completo, documento_url FROM analisis_licitaciones")
        rows = cursor.fetchall()
        columnas = ["ID", "Título", "Estado", "Puntuación", "Notas", "Reporte", "Documento_URL"]
        df = pd.DataFrame(rows, columns=columnas)
        cursor.close()
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error BD: {e}")
        return pd.DataFrame()

df = obtener_licitaciones()

def obtener_documentos_vinculados(id_proceso):
    try:
        conn = psycopg2.connect(
            host=st.secrets["DB_HOST"], database=st.secrets["DB_NAME"],
            user=st.secrets["DB_USER"], password=st.secrets["DB_PASS"]
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT id, nombre_archivo, documento_url, mime_type 
            FROM documentos_licitacion 
            WHERE id_proceso = %s 
            ORDER BY fecha_subida DESC
        """, (id_proceso,))
        docs = cur.fetchall()
        cur.close()
        conn.close()
        return docs
    except Exception as e:
        st.error(f"Error BD: {e}")
        return pd.DataFrame()
    

def eliminar_documento_api(id_doc):
    try:
        # Llamamos al endpoint de eliminar que creamos en el main.py
        response = requests.post(
            f"{API_URL}/eliminar_documento", 
            data={"id_doc": id_doc}
        )
        return response.status_code == 200
    except Exception as e:
        st.error(f"Error al conectar con la API: {e}")
        return False
    

def obtener_enlace_descarga(id_doc):
    try:
        res = requests.post(f"{API_URL}/generar_descarga", data={"id_doc": id_doc})
        if res.status_code == 200:
            return res.json().get("url_descarga")
    except:
        return None

# --- 2. BARRA LATERAL: REGISTRAR NUEVA ---
with st.sidebar:
    st.header("➕ Registrar Licitación")
    st.markdown("Crea el registro para luego subirle documentos.")
    id_input = st.text_input("ID Proceso (ej. DGCP-2026)")
    titulo_input = st.text_input("Título")
    
    if st.button("Crear Registro"):
        # Llamamos a la API sin archivo solo para crear el registro
        res = requests.post(API_URL, data={"id_proceso": id_input, "titulo": titulo_input})
        if res.status_code == 200:
            st.success("Licitación creada. Búscala en el panel para subir su pliego.")
            st.cache_data.clear()
            st.rerun()

if df.empty:
    st.info("No hay licitaciones. Registra una en el menú lateral.")
    st.stop()

# --- 3. PANEL CENTRAL DE LICITACIONES ---
st.subheader("📋 Portafolio de Licitaciones")

for index, row in df.iterrows():
    score = row["Puntuación"] if pd.notna(row["Puntuación"]) else 0
    icono = "🟢" if score >= 8 else "🟡" if score >= 5 else "🔴"
    if score == 0: icono = "⚪" # Para las nuevas sin analizar
    
    with st.expander(f"{icono} {row['ID']} - {row['Título']} (Score: {score})"):
        
        # Creamos 3 pestañas para organizar la información
        tab1, tab2, tab3 = st.tabs(["📊 Análisis de AI", "📝 Notas adicionales", "📁 Repositorio de Documentos"])
        
        # PESTAÑA 1: ANÁLISIS
        with tab1:
            st.write(f"**Estado:** {row['Estado']}")
            st.markdown(f"**Conclusión de Gemini:**\n> {row['Reporte'] if pd.notna(row['Reporte']) else 'Sin análisis aún.'}")
            
            if st.button("🤖 Ejecutar Análisis Global", key=f"btn_run_{row['ID']}"):
                with st.spinner("El agente está procesando todo el expediente..."):
                    res_analisis = requests.post(f"{API_URL}/analizar", data={"id_proceso": row['ID']})
                    if res_analisis.status_code == 200:
                        st.success("Análisis completado.")
                        st.cache_data.clear()
                        st.rerun()
                        
            if st.button("📄 Preparar PDF Ejecutivo", key=f"pdf_prep_{row['ID']}"):
                with st.spinner("Creando PDF en el servidor..."):
                    res_pdf = requests.post(f"{API_URL}/generar_reporte_pdf", data={"id_proceso": row['ID']})
                    if res_pdf.status_code == 200:
                        st.session_state[f"pdf_data_{row['ID']}"] = res_pdf.content
                    else:
                        st.error(f"Error al generar el PDF (HTTP {res_pdf.status_code}): {res_pdf.text}")
            
            if f"pdf_data_{row['ID']}" in st.session_state:
                st.download_button(
                    label="📥 Descargar Reporte PDF",
                    data=st.session_state[f"pdf_data_{row['ID']}"],
                    file_name=f"Reporte_{row['ID']}.pdf",
                    mime="application/pdf",
                    key=f"dl_pdf_{row['ID']}"
                )

            # if st.button("🔄 Ejecutar Re-evaluación IA", key=f"eval_{row['ID']}"):
            #    with st.spinner("Gemini está leyendo el documento en Cloud Storage..."):
            #        res = requests.post(API_URL, data={"id_proceso": row['ID']})
            #        if res.status_code == 200:
            #            st.success("Análisis completado.")
            #            st.cache_data.clear()
            #            st.rerun() 
        
        # PESTAÑA 2: NOTAS
        with tab2:
            nota_actual = row['Notas'] if pd.notna(row['Notas']) else ""
            nueva_nota = st.text_area("Contexto Estratégico (Modifica el pensamiento de la IA):", value=nota_actual, key=f"nota_{row['ID']}")
            
            # Nota: Asegúrate de tener tu endpoint de /guardar_notas en el main.py funcionando
            if st.button("💾 Sincronizar Notas", key=f"sync_{row['ID']}"):
                st.info("Notas actualizadas (Requiere que el endpoint /guardar_notas esté activo).")
                
        # PESTAÑA 3: DOCUMENTOS (LO NUEVO)
        with tab3:
            st.subheader("📂 Expediente Digital")
    
            docs_vinculados = obtener_documentos_vinculados(row['ID'])
            
            if docs_vinculados:
                with st.expander(f"Ver {len(docs_vinculados)} documentos archivados", width="stretch", expanded=False):
                    for doc_id, nombre, url, mime in docs_vinculados:
                        col_nom, col_desc, col_bor = st.columns([2, 0.05, 0.05])
                        
                        with col_nom:
                            st.caption(f"📄 {nombre}")
                        
                        with col_desc:
                            # Botón de descarga (usando la URL de GCS o proxy)
                            # Nota: Para descarga directa desde GCS se requiere un Signed URL
                            url_segura = obtener_enlace_descarga(doc_id)
                            if url_segura:
                                st.link_button("📥", url_segura, help="Descargar desde GCS", use_container_width=False)
                            else:
                                st.error("Error de enlace")
                            #st.link_button("Descargar", url, use_container_width=True)
                        
                        with col_bor:
                            if st.button("🗑️", key=f"del_{doc_id}", help="Eliminar de GCS y Base de Datos", type="secondary"):
                                with st.spinner("Eliminando..."):
                                    if eliminar_documento_api(doc_id):
                                        st.toast(f"✅ {nombre} eliminado correctamente")
                                        st.cache_data.clear() # Limpiamos caché para ver cambios
                                        st.rerun() # Refrescamos la UI
                                    else:
                                        st.error("No se pudo eliminar el archivo.")
            else:
                st.info("No hay documentos vinculados aún.")
                
            st.divider()
            archivo_nuevo = st.file_uploader("Agregar archivo al expediente", key=f"repo_{row['ID']}")
            if st.button("📁 Archivar Documento", key=f"btn_arc_{row['ID']}"):
                if archivo_nuevo:
                    files = {"archivo": (archivo_nuevo.name, archivo_nuevo.getvalue(), archivo_nuevo.type)}
                    requests.post(f"{API_URL}/subir_documento", data={"id_proceso": row['ID']}, files=files)
                    st.success("Guardado en el repositorio.")
                        
                else:
                    st.error("Por favor adjunta un archivo primero.")