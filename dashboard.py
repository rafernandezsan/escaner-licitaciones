import streamlit as st
import pandas as pd
import requests
import psycopg2

# Configuración de la página
st.set_page_config(page_title="Radar de Licitaciones TI", page_icon="🎯", layout="wide")

# URL de tu API en Cloud Run
API_URL = "https://langgraph-orchestrator-worker-1066450737358.us-east1.run.app" 

st.title("🎯 Radar de Licitaciones DGCP")
st.markdown("Plataforma de análisis impulsada por Gemini 2.5 Flash y PostgreSQL")

# --- 1. CONEXIÓN REAL A LA BASE DE DATOS ---
@st.cache_data(ttl=10) # Refresca los datos cada 10 segundos
def obtener_licitaciones():
    try:
        # Conectamos usando los secretos de Streamlit
        conn = psycopg2.connect(
            host=st.secrets["DB_HOST"],
            database=st.secrets["DB_NAME"],
            user=st.secrets["DB_USER"],
            password=st.secrets["DB_PASS"]
        )
        cursor = conn.cursor()
        
        # Traemos todos los registros de la tabla
        cursor.execute("SELECT id_proceso, titulo, estado, puntuacion, es_objetivo, notas FROM analisis_licitaciones")
        rows = cursor.fetchall()
        
        # Convertimos los datos a un formato que Streamlit entienda (DataFrame)
        columnas = ["ID", "Título", "Estado", "Puntuación", "Es Objetivo", "Notas"]
        df = pd.DataFrame(rows, columns=columnas)
        
        cursor.close()
        conn.close()
        return df
    
    except Exception as e:
        st.error(f"Error conectando a la base de datos: {e}")
        # Retorna un DataFrame vacío si hay error para que no se caiga la app
        return pd.DataFrame(columns=["ID", "Título", "Estado", "Puntuación", "Es Objetivo", "Notas"])

df = obtener_licitaciones()

# Si no hay datos todavía, mostramos un aviso
if df.empty:
    st.info("Aún no hay licitaciones analizadas en la base de datos. Envía una desde la terminal o conecta el scraper de la DGCP.")
    st.stop()

# --- 2. PANEL DE MÉTRICAS (KPIs) ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Encontradas", len(df))
col2.metric("🎯 Alta Prioridad (Score > 8)", len(df[df["Puntuación"] >= 8]))
col3.metric("⏳ Pendientes", len(df[df["Estado"] == "Pendiente"]))
col4.metric("❌ Errores OCR/IA", len(df[df["Estado"] == "Error"]))

st.divider()

# --- 3. FILTROS ---
filtro_estado = st.selectbox("Filtrar por Estado:", ["Todas", "Analizada", "Pendiente", "Error"])

if filtro_estado != "Todas":
    df_filtrado = df[df["Estado"] == filtro_estado]
else:
    df_filtrado = df

# --- 4. LISTA Y PANEL DE ACCIONES INTERACTIVAS ---
st.subheader("📋 Licitaciones Detectadas")

for index, row in df_filtrado.iterrows():
    # Manejar los None de la BD de forma segura
    score = row["Puntuación"] if pd.notna(row["Puntuación"]) else 0
    icono = "🟢" if score >= 8 else "🟡" if score >= 5 else "🔴"
    
    with st.sidebar:
        st.header("📤 Nueva Licitación")
        id_input = st.text_input("ID Proceso")
        titulo_input = st.text_input("Título")
        archivo_subido = st.file_uploader("Subir Pliego (PDF)", type="pdf")
        
        if st.button("🚀 Iniciar Análisis"):
            # Usamos 'files' para enviar el archivo real
            files = {"archivo": (archivo_subido.name, archivo_subido.getvalue(), "application/pdf")}
            data = {"id_proceso": id_input, "titulo": titulo_input}
            
            res = requests.post(API_URL, data=data, files=files)
            st.success("Archivo en la nube. Análisis iniciado.")

    with st.expander(f"{icono} {row['ID']} - {row['Título']} (Score: {score})"):
        st.write(f"**Estado:** {row['Estado']}")
        
        c1, c2, c3, c4 = st.columns(4)
        
        with c1:
            # En el botón de 'Re-evaluar' dentro de la tabla
            if st.button("🔄 Re-evaluar", key=f"re_{row['ID']}"):
                with st.spinner("Consultando repositorio de documentos..."):
                    # Solo mandamos el ID, el backend tiene el resto en GCS y SQL
                    res = requests.post(API_URL, data={"id_proceso": row['ID']})
                    st.rerun()
        
        with c2:
            st.download_button(
                label="📄 Descargar PDF",
                data=b"Simulacion de PDF",
                file_name=f"{row['ID']}_pliego.pdf",
                mime="application/pdf",
                key=f"dl_{row['ID']}"
            )
            
        with c3:
            resumen_compartir = f"🚨 *Oportunidad DGCP*\n*ID:* {row['ID']}\n*Proyecto:* {row['Título']}\n*Score:* {score}/10"
            st.code(resumen_compartir, language="markdown")

        st.markdown("### 📝 Notas")
        nota_actual = row['Notas'] if pd.notna(row['Notas']) else ""
        nueva_nota = st.text_area("Añade contexto estratégico:", value=nota_actual, key=f"n_{row['ID']}")

        if st.button("💾 Sincronizar Nota", key=f"btn_{row['ID']}"):
            with st.spinner('Guardando en la nube...'):
                res = requests.post(f"{API_URL}/guardar_notas", json={
                    "id_proceso": row['ID'],
                    "notas": nueva_nota
                })
                if res.status_code == 200:
                    st.success("¡Nota guardada! Gemini la usará en la próxima re-evaluación.")
                    st.cache_data.clear() # Refresca la tabla