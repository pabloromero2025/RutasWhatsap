import streamlit as st
import pdfplumber
import pandas as pd
import re
import requests
import time
from geopy.geocoders import ArcGIS
from geopy.distance import geodesic
import io
import folium
from streamlit_folium import st_folium
from folium import plugins

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Sistemas Inteligentes | Logística", page_icon="🧠", layout="wide")

# --- ESTILOS CSS CON LOGO PERSONALIZADO ---
st.markdown("""
    <style>
    /* Logo en la esquina */
    .brand-logo {
        position: absolute;
        top: -50px;
        left: 0;
        display: flex;
        align-items: center;
        gap: 10px;
        background: rgba(255,255,255,0.1);
        padding: 10px 20px;
        border-radius: 10px;
    }
    .logo-icon {
        background: #00d2ff;
        width: 35px;
        height: 35px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        color: #0f2027;
        box-shadow: 0 0 15px #00d2ff;
    }
    .brand-name {
        font-family: 'Segoe UI', sans-serif;
        font-weight: 800;
        color: white;
        letter-spacing: 1px;
        font-size: 18px;
    }

    /* Hero Header */
    .hero-container {
        background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
        padding: 60px 40px 40px 40px;
        border-radius: 20px;
        color: white;
        text-align: center;
        margin-bottom: 30px;
        position: relative;
    }
    
    .stButton>button {
        border-radius: 12px;
        background: #203a43;
        color: white;
        border: 1px solid #00d2ff;
    }
    </style>
    
    <div class="hero-container">
        <div class="brand-logo">
            <div class="logo-icon">SI</div>
            <div class="brand-name">SISTEMAS INTELIGENTES</div>
        </div>
        <h1>🧠 Optimizador de Rutas Estratégico</h1>
        <p>Soluciones de software para logística de alta precisión</p>
    </div>
    """, unsafe_allow_html=True)

# --- FUNCIONES (Mantenemos la lógica interna) ---
def extraer_telefono(texto):
    patron = r'(?:011|11|15)[\s.-]?\d{2,4}[\s.-]?\d{4,6}'
    matches = re.findall(patron, texto)
    for m in matches:
        num_limpio = re.sub(r'\D', '', m)
        if num_limpio.startswith('011'): num_limpio = '11' + num_limpio[3:]
        if len(num_limpio) == 10: return num_limpio
    return None

def limpieza_profunda_direccion(direccion):
    dir_limpia = re.sub(r'^\d+[\s,]+\d+\s+', '', direccion)
    palabras_ruido = [r'\bCalle\b', r'\bAvenida\b', r'\bAv\b', r'\bGral\b', r'\bGeneral\b']
    for p in palabras_ruido:
        dir_limpia = re.sub(p, '', dir_limpia, flags=re.IGNORECASE)
    return dir_limpia.strip()

def obtener_ruta_osrm(c1, c2):
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{c1[1]},{c1[0]};{c2[1]},{c2[0]}?overview=false"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get('code') == 'Ok':
            return round(data['routes'][0]['distance'] / 1000, 2), round(data['routes'][0]['duration'] / 60)
    except: return None, None
    return 0.0, 0

def optimizar_orden(coords_inicio, lista_puntos):
    puntos_pendientes = lista_puntos.copy()
    ruta_optimizada = []
    punto_actual = coords_inicio
    while puntos_pendientes:
        mas_cercano = min(puntos_pendientes, key=lambda x: geodesic(punto_actual, x['Coords']).km)
        ruta_optimizada.append(mas_cercano)
        punto_actual = mas_cercano['Coords']
        puntos_pendientes.remove(mas_cercano)
    return ruta_optimizada

# --- ESTADO ---
if 'df_final' not in st.session_state:
    st.session_state.df_final = None

# --- SIDEBAR ---
with st.sidebar:
    st.markdown("### 🖥️ Panel de Control")
    origen_input = st.text_input("📍 Origen", "Obelisco, Buenos Aires")
    fin_input = st.text_input("🏁 Retorno", "Obelisco, Buenos Aires")
    st.markdown("---")
    archivo_subido = st.file_uploader("Cargar PDF de Entregas", type="pdf")
    
    if st.button("🗑️ Resetear Datos", use_container_width=True):
        st.session_state.df_final = None
        st.rerun()

# --- LÓGICA DE PROCESAMIENTO ---
if archivo_subido and st.session_state.df_final is None:
    with st.status("Analizando datos para Sistemas Inteligentes...", expanded=True):
        geolocator = ArcGIS()
        loc_o = geolocator.geocode(origen_input)
        loc_f = geolocator.geocode(fin_input)
        c_inicio = [loc_o.latitude, loc_o.longitude]
        c_fin = [loc_f.latitude, loc_f.longitude]

        puntos_pdf = []
        with pdfplumber.open(archivo_subido) as pdf:
            for page in pdf.pages:
                texto = page.extract_text()
                if not texto: continue
                bloques = re.split(r'\n(?=\d+[\s,]+\d+)', texto)
                for b in bloques:
                    lineas = b.strip().split('\n')
                    if re.match(r'^(\d+)[\s,]+(\d+)', lineas[0]):
                        tel = extraer_telefono(b)
                        for l in lineas:
                            if "Argentina" in l:
                                partes = [p.strip() for p in l.split(',')]
                                dir_b = f"{limpieza_profunda_direccion(partes[0])}, {partes[2]}, Argentina"
                                loc = geolocator.geocode(dir_b)
                                if loc:
                                    puntos_pdf.append({"Direccion": partes[0], "Coords": [loc.latitude, loc.longitude], "Telefono": tel if tel else ""})
                                break

        ruta_opt = optimizar_orden(c_inicio, puntos_pdf)
        lista = [{"Tipo": "SALIDA", "Direccion": origen_input, "Coords": c_inicio, "Telefono": ""}] + \
                [{"Tipo": "ENTREGA", "Direccion": p['Direccion'], "Coords": p['Coords'], "Telefono": p['Telefono']} for p in ruta_opt] + \
                [{"Tipo": "LLEGADA", "Direccion": fin_input, "Coords": c_fin, "Telefono": ""}]
        st.session_state.df_final = pd.DataFrame(lista)

# --- MAPA Y EDITOR ---
if st.session_state.df_final is not None:
    df = st.session_state.df_final
    col_mapa, col_info = st.columns([2, 1])

    with col_info:
        st.markdown("### 📋 Planificación Final")
        edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True, key="editor_si")
        if st.button("🔄 Aplicar y Recalcular Mapa"):
            st.session_state.df_final = edited_df
            st.rerun()

    with col_mapa:
        m = folium.Map(location=df.iloc[0]['Coords'], zoom_start=12, tiles="cartodbpositron")
        folium.PolyLine(df['Coords'].tolist(), color="#00d2ff", weight=5, opacity=0.8).add_to(m)

        for i, row in df.iterrows():
            lat, lon = row['Coords']
            g_maps = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"
            
            tel_html = ""
            if row['Telefono']:
                tel_html = f"""
                <div style="display:flex; gap:5px; margin-top:10px;">
                    <a href="https://wa.me/549{row['Telefono']}?text=Sistemas Inteligentes: Su pedido está en camino." target="_blank" 
                       style="flex:1; background:#25D366; color:white; padding:8px; border-radius:5px; text-decoration:none; text-align:center; font-weight:bold; font-size:11px;">WSP</a>
                    <a href="tel:{row['Telefono']}" 
                       style="flex:1; background:#333; color:white; padding:8px; border-radius:5px; text-decoration:none; text-align:center; font-weight:bold; font-size:11px;">Llamar</a>
                </div>
                """
            
            pop_html = f"""
            <div style="font-family: sans-serif; width:200px; border-top: 3px solid #00d2ff;">
                <b style="color:#203a43;">Parada #{i}</b><br>
                <p style="margin:5px 0; font-size:11px;">{row['Direccion']}</p>
                <a href="{g_maps}" target="_blank" 
                   style="display:block; background:#4285F4; color:white; padding:8px; border-radius:5px; text-decoration:none; text-align:center; font-weight:bold; font-size:11px;">📍 Google Maps</a>
                {tel_html}
            </div>
            """
            
            color = "green" if row['Tipo'] == "SALIDA" else ("red" if row['Tipo'] == "LLEGADA" else "blue")
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(pop_html, max_width=250),
                icon=plugins.BeautifyIcon(number=i if row['Tipo']=="ENTREGA" else None, border_color=color, text_color=color, icon_shape='marker')
            ).add_to(m)

        st_folium(m, width="100%", height=600, key="mapa_si")
