import streamlit as st
import pdfplumber
import pandas as pd
import re
import requests
import time
from geopy.geocoders import ArcGIS
from geopy.distance import geodesic
import io

# --- FUNCIONES DE LÓGICA (Tu código) ---

def limpieza_profunda_direccion(direccion):
    dir_limpia = re.sub(r'^\d+[\s,]+\d+\s+', '', direccion)
    palabras_ruido = [
        r'\bCalle\b', r'\bAvenida\b', r'\bAv\b', r'\bGral\b', 
        r'\bGeneral\b', r'\bJose G\.\b', r'\bEnrique\b', r'\bLazaro\b'
    ]
    for p in palabras_ruido:
        dir_limpia = re.sub(p, '', dir_limpia, flags=re.IGNORECASE)
    return dir_limpia.strip()

def obtener_ruta_osrm(coords_1, coords_2):
    try:
        lat1, lon1 = coords_1.split(", ")
        lat2, lon2 = coords_2.split(", ")
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1.strip()},{lat1.strip()};{lon2.strip()},{lat2.strip()}?overview=false"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get('code') == 'Ok':
            distancia = round(data['routes'][0]['distance'] / 1000, 2)
            segundos = data['routes'][0]['duration']
            minutos = round(segundos / 60)
            return distancia, f"{minutos} min"
    except:
        return None, None
    return 0.0, "0 min"

# --- INTERFAZ DE LA PÁGINA WEB ---

st.set_page_config(page_title="Generador de Hoja de Ruta", page_icon="🚚")
st.title("🚚 Generador de Hoja de Ruta")
st.markdown("Sube tu archivo **PDF** y descarga el **Excel** con coordenadas, distancias reales y tiempos.")

archivo_subido = st.file_uploader("Elige un archivo PDF", type="pdf")

if archivo_subido is not None:
    if st.button("Procesar Archivo"):
        with st.spinner('Procesando PDF y calculando rutas... por favor espera.'):
            datos_extraidos = []
            geolocator = ArcGIS()
            
            # 1. Procesar PDF
            with pdfplumber.open(archivo_subido) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if not texto: continue
                    bloques = re.split(r'\n(?=\d+[\s,]+\d+)', texto)
                    for bloque in bloques:
                        lineas = bloque.strip().split('\n')
                        if len(lineas) < 2: continue
                        match_indices = re.match(r'^(\d+)[\s,]+(\d+)', lineas[0])
                        if not match_indices: continue
                        
                        orden_id, parada = match_indices.group(1), match_indices.group(2)
                        for linea in lineas:
                            if "Argentina" in linea or re.search(r'\d{4},', linea):
                                partes = [p.strip() for p in linea.split(',')]
                                if len(partes) >= 4:
                                    dir_original = re.sub(r'^\d+[\s,]+\d+\s+', '', partes[0])
                                    dir_para_buscar = limpieza_profunda_direccion(partes[0])
                                    datos_extraidos.append({
                                        "Direccion": dir_original, "CP": partes[1],
                                        "Localidad": partes[2], "Provincia": partes[3],
                                        "Orden": int(orden_id), "Parada": int(parada),
                                        "Busqueda": f"{dir_para_buscar}, {partes[2]}, Argentina"
                                    })
                                    break

            df = pd.DataFrame(datos_extraidos).sort_values(by="Parada").reset_index(drop=True)

            # 2. Coordenadas
            coords_list = []
            progreso = st.progress(0)
            for i, row in df.iterrows():
                try:
                    location = geolocator.geocode(row['Busqueda'], timeout=10)
                    coords_list.append(f"{location.latitude}, {location.longitude}" if location else "No encontrada")
                except:
                    coords_list.append("No encontrada")
                progreso.progress((i + 1) / len(df))
                time.sleep(0.1)

            df["Coordenadas"] = coords_list

            # 3. Distancias y Tiempos
            distancias_reales = [0.0]
            tiempos = ["0"]
            for i in range(1, len(df)):
                c_ant, c_act = df.loc[i-1, 'Coordenadas'], df.loc[i, 'Coordenadas']
                if "No encontrada" not in c_ant and "No encontrada" not in c_act:
                    dist, tiempo = obtener_ruta_osrm(c_ant, c_act)
                    if dist is None:
                        dist = round(geodesic(c_ant, c_act).kilometers, 2)
                        tiempo = "N/A"
                else:
                    dist, tiempo = 0.0, "0"
                distancias_reales.append(dist)
                tiempos.append(tiempo)
                time.sleep(0.4)

            df['Distancia_KM'] = distancias_reales
            df['Tiempo'] = tiempos
            df.drop(columns=['Busqueda'], inplace=True)

            # --- Mostrar resultado y Botón de Descarga ---
            st.success("¡Proceso completado!")
            st.dataframe(df)

            # Convertir DataFrame a Excel en memoria
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name='Hoja de Ruta')
            
            st.download_button(
                label="📥 Descargar Excel",
                data=output.getvalue(),
                file_name="Hoja_de_Ruta_Procesada.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
 