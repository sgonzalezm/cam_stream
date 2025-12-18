from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from datetime import datetime, timedelta
import glob
import re

app = FastAPI()

# CONFIGURACIÓN - IMPORTANTE: AJUSTA ESTA RUTA
VIDEO_ROOT_DIR = "/media/diego/camaras"  # El directorio raíz que contiene las carpetas CamX_YYYY-MM-DD
VIDEO_EXTENSION = ".mp4"
# Cámaras soportadas (puedes añadir más si es necesario)
CAMERAS = ["Cam1", "Cam2"] 
DATE_FORMAT = "%Y-%m-%d"
FOLDER_PATTERN = r"(Cam\d+)_(\d{4}-\d{2}-\d{2})" # Patrón para la carpeta (ej: Cam1_2025-12-08)

# Servir archivos estáticos
# (Asumiendo que 'static' está en el mismo nivel que este script)
app.mount("/static", StaticFiles(directory="static"), name="static")


def extract_info_from_path(file_path):
    try:
        # Extraer el path relativo al directorio raíz
        relative_path = os.path.relpath(file_path, VIDEO_ROOT_DIR)
        
        # Obtener la carpeta principal (ej. Cam1_2025-12-08)
        folder_name = relative_path.split(os.sep)[0]
        filename = os.path.basename(file_path)

        # 1. Extraer CamID y Fecha de la carpeta (mantenemos esto para el filtrado)
        match = re.match(FOLDER_PATTERN, folder_name)
        if not match:
            print(f"Error: La carpeta {folder_name} no coincide con el patrón esperado.")
            return None

        camera_id = match.group(1) # Ej: Cam1
        date_folder_str = match.group(2)   # Ej: 2025-12-08
        
        # 2. Intentar extraer el timestamp completo del NOMBRE DEL ARCHIVO
        # Patrón típico: YYYY-MM-DD_HH-MM-SS
        time_match = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})', filename)
        
        if time_match:
             # Si encontramos el patrón completo: YYYY-MM-DD_HH-MM-SS
             date_part = time_match.group(1)
             time_part = time_match.group(2).replace('-', ':') # Convertir 17-46-33 a 17:46:33
             datetime_str = f"{date_part} {time_part}"
             # Usamos el formato completo para parsear
             file_time = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
             
        else:
             # Si el nombre del archivo no tiene fecha/hora clara, usar el mtime
             # y la fecha de la carpeta para ser consistente.
             file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
             
        # El "nombre de archivo" único para el front-end será la ruta relativa
        unique_filename = os.path.join(folder_name, filename).replace(os.sep, '__')

        return {
            "camera_id": camera_id,
            "date": date_folder_str, # Usamos la fecha de la carpeta para el índice de fechas
            "timestamp": file_time,
            "filename": filename,
            "unique_path": unique_filename, 
            "full_path": file_path
        }
    except Exception as e:
        # Imprimir el error con más contexto, incluyendo el string que falló, si aplica
        print(f"Error al extraer info de {file_path}: {e}")
        return None

def find_all_video_files():
    """Busca recursivamente todos los videos en la nueva estructura de carpetas."""
    all_video_data = []
    
    # Patrón de búsqueda para todas las carpetas que coincidan con CamX_YYYY-MM-DD
    # y los archivos .mp4 dentro de ellas
    # Ejemplo de patrón: /media/diego/camaras/Cam*_????-??-??/*.mp4
    search_pattern = os.path.join(VIDEO_ROOT_DIR, f"Cam*_{DATE_FORMAT.replace('%Y', '????').replace('%m', '??').replace('%d', '??')}", f"*{VIDEO_EXTENSION}")
    
    print(f"Patrón de búsqueda: {search_pattern}")

    for file_path in glob.glob(search_pattern):
        video_data = extract_info_from_path(file_path)
        if video_data:
            # Añadir tamaño y timestamp en formato ISO para el JSON
            video_data["size_mb"] = round(os.path.getsize(file_path) / (1024 * 1024), 2)
            video_data["timestamp_iso"] = video_data["timestamp"].isoformat()
            all_video_data.append(video_data)
            
    return all_video_data


@app.get("/")
async def read_root():
    """Página principal"""
    return FileResponse("static/interface.html")


@app.get("/api/videos/recent")
async def get_recent_videos(hours: int = 2, camera: str = None):
    """Obtener videos de las últimas N horas, opcionalmente filtrados por cámara"""
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours)
        videos = find_all_video_files()
        filtered_videos = []
        
        for video in videos:
            if video["timestamp"] >= cutoff_time:
                # Filtrar por cámara si se especifica
                if camera is None or video["camera_id"].lower() == camera.lower():
                    filtered_videos.append({
                        "camera_id": video["camera_id"],
                        "date": video["date"],
                        "filename": video["unique_path"], # Usar la ruta única para el frontend
                        "timestamp": video["timestamp_iso"],
                        "size_mb": video["size_mb"]
                    })
        
        # Ordenar por timestamp (más reciente primero)
        filtered_videos.sort(key=lambda x: x["timestamp"], reverse=True)
        return filtered_videos
        
    except Exception as e:
        print(f"Error en get_recent_videos: {e}")
        raise HTTPException(status_code=500, detail=f"Error del servidor: {str(e)}")


@app.get("/api/videos/dates")
async def get_available_dates(camera: str = None):
    """Obtener fechas disponibles, opcionalmente filtradas por cámara"""
    try:
        videos = find_all_video_files()
        dates_cameras = set()
        
        for video in videos:
            if camera is None or video["camera_id"].lower() == camera.lower():
                # Almacenar tupla (fecha, camara) para asegurar que la cámara tiene video ese día
                dates_cameras.add((video["date"], video["camera_id"]))
                
        # Organizar por cámara y luego por fecha (más reciente primero)
        result = {}
        for date_str, cam_id in dates_cameras:
            if cam_id not in result:
                result[cam_id] = []
            result[cam_id].append(date_str)
            
        # Ordenar las fechas dentro de cada cámara
        for cam_id in result:
             result[cam_id].sort(reverse=True)
             
        return result
        
    except Exception as e:
        print(f"Error en get_available_dates: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.get("/api/videos/by-date")
async def get_videos_by_date(date: str, camera: str = None):
    """Obtener videos por fecha específica, opcionalmente filtrados por cámara"""
    try:
        videos = find_all_video_files()
        filtered_videos = []
        
        for video in videos:
            if video["date"] == date:
                if camera is None or video["camera_id"].lower() == camera.lower():
                    filtered_videos.append({
                        "camera_id": video["camera_id"],
                        "date": video["date"],
                        "filename": video["unique_path"],
                        "timestamp": video["timestamp_iso"],
                        "size_mb": video["size_mb"]
                    })
        
        filtered_videos.sort(key=lambda x: x["timestamp"])
        return filtered_videos
        
    except Exception as e:
        print(f"Error en get_videos_by_date: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# ---- ENDPOINTS DE ACCESO A ARCHIVOS ----
# Estos endpoints necesitan la ruta única para reconstruir la ruta física del archivo.

def get_physical_path(unique_path: str):
    """Convierte la ruta única (CamX_YYYY-MM-DD__filename.mp4) a la ruta física."""
    # Reemplazar el separador doble '__' con el separador del sistema ('/' o '\')
    relative_path = unique_path.replace('__', os.sep)
    file_path = os.path.join(VIDEO_ROOT_DIR, relative_path)
    return file_path


@app.get("/api/stream/{unique_path}")
async def stream_video(unique_path: str):
    """Servir video para reproducción (usa la ruta única)."""
    file_path = get_physical_path(unique_path)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path, media_type="video/mp4")
    
    raise HTTPException(status_code=404, detail=f"Video no encontrado: {unique_path}")


@app.get("/api/download/{unique_path}")
async def download_video(unique_path: str):
    """Descargar video (usa la ruta única)."""
    file_path = get_physical_path(unique_path)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        # Intentar obtener el nombre original del archivo para la descarga
        original_filename = os.path.basename(unique_path).replace('__', os.sep).split(os.sep)[-1]
        
        return FileResponse(
            file_path,
            media_type="video/mp4",
            filename=original_filename # Nombre que verá el usuario al descargar
        )
    
    raise HTTPException(status_code=404, detail=f"Video no encontrado: {unique_path}")


@app.get("/api/debug")
async def debug_info():
    """Endpoint de diagnóstico"""
    try:
        videos = find_all_video_files()
        
        info = {
            "video_root_directory": VIDEO_ROOT_DIR,
            "directory_exists": os.path.exists(VIDEO_ROOT_DIR),
            "total_videos": len(videos),
            "sample_videos": []
        }
        
        # Mostrar primeros 5 archivos de la lista completa
        for video in videos[:5]:
            info["sample_videos"].append({
                "camera_id": video["camera_id"],
                "date": video["date"],
                "filename": video["filename"],
                "unique_path": video["unique_path"],
                "timestamp": video["timestamp_iso"],
                "size_mb": video["size_mb"],
                "full_path_exists": os.path.exists(video["full_path"])
            })
            
        return info
        
    except Exception as e:
        return {"error": f"Error en debug: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    # NOTA: uvicorn debe ejecutarse con el nombre de archivo, ej: uvicorn main:app --reload
    uvicorn.run(app, host="0.0.0.0", port=8000)