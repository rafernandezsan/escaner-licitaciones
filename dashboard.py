import streamlit as st
import pandas as pd
import requests
import psycopg2

# Configuración de la página
st.set_page_config(page_title="Radar de Licitaciones", page_icon="🎯", layout="wide")
API_URL = "https://langgraph-orchestrator-worker-1066450737358.us-east1.run.app" # <-- Reemplaza por tu URL real

st.title("🎯 Radar de Licitaciones DGCP")

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
        tab1, tab2, tab3 = st.tabs(["📊 Análisis e IA", "📝 Memoria del Consultor", "📁 Repositorio de Documentos"])
        
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
            st.markdown("### Documentos Vinculados")
            if pd.notna(row['Documento_URL']) and row['Documento_URL']:
                st.success(f"📄 **Pliego actual en la nube:** `{row['Documento_URL']}`")
            else:
                st.warning("No hay ningún pliego vinculado a este proceso.")
                
            st.divider()
            archivo_nuevo = st.file_uploader("Agregar archivo al expediente", key=f"repo_{row['ID']}")
            if st.button("📁 Archivar Documento", key=f"btn_arc_{row['ID']}"):
                if archivo_nuevo:
                    files = {"archivo": (archivo_nuevo.name, archivo_nuevo.getvalue(), archivo_nuevo.type)}
                    requests.post(f"{API_URL}/subir_documento", data={"id_proceso": row['ID']}, files=files)
                    st.success("Guardado en el repositorio.")
            
            if st.button("📤 Procesar con IA Multimodal", key=f"btn_up_{row['ID']}"):
                if archivo_comodin:
                    with st.spinner("Gemini analizando el archivo..."):
                        payload = {"id_proceso": row['ID'], "titulo": row['Título']}
                        # Pasamos el type original del archivo (image/jpeg, application/pdf, etc)
                        files = {"archivo": (archivo_comodin.name, archivo_comodin.getvalue(), archivo_comodin.type)}
                        
                        res = requests.post(API_URL, data=payload, files=files)
                        if res.status_code == 200:
                            st.success(f"Procesado como {archivo_comodin.type}")
                            st.cache_data.clear()
                            st.rerun()
                else:
                    st.error("Por favor adjunta un archivo primero.")