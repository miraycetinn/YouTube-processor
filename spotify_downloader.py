import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp
import sqlite3
import os
import re
from dotenv import load_dotenv
import logging
from datetime import timedelta
import time # Rate limiting için eklendi

# Hata ayıklama ve bilgilendirme loglarını ayarlama
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# .env dosyasındaki değişkenleri yükle
load_dotenv()

# --- Yapılandırma ---
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
DATABASE_NAME = "muzik_kutuphanesi.db"
DOWNLOAD_FOLDER = "indirilen_sarkilar"
SONG_LIST_FILE = "sarki_listesi.txt" # Okunacak şarkı listesi dosyası
DURATION_TOLERANCE_SECONDS = 10
FORBIDDEN_KEYWORDS = [
    "cover", "remix", "live", "acoustic", "instrumental", "lyrics",
    "parody", "tutorial", "reaction", "karaoke", "mashup", "canlı",
    "akustik", "enstrümantal", "sözleri", "parodi", "ders", "tepki",
    "konser", "remiks", "official video" # 'official audio' tercih edilebilir
]
SPOTIFY_SEARCH_LIMIT = 1 # Spotify aramasında kaç sonuç getirileceği (genelde 1 yeterli)
API_REQUEST_DELAY = 0.5 # API istekleri arasına konulacak saniye cinsinden gecikme (rate limiting için)
# --------------------

# Spotify API İstemcisi (global olarak tanımlanabilir)
spotify_api = None
if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET:
    try:
        auth_manager = SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET)
        spotify_api = spotipy.Spotify(auth_manager=auth_manager)
        logging.info("Spotify API istemcisi başarıyla oluşturuldu.")
    except Exception as e:
        logging.error(f"Spotify API istemcisi oluşturulurken hata: {e}")
        spotify_api = None
else:
    logging.error("Spotify Client ID veya Secret bulunamadı. Lütfen .env dosyasını kontrol edin.")


# İndirme klasörünü oluştur
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def setup_database():
    """Veritabanını ve tabloyu oluşturur (eğer yoksa)."""
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spotify_id TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            album TEXT,
            spotify_duration_ms INTEGER,
            youtube_url TEXT,
            downloaded_file_path TEXT,
            album_art_url TEXT,
            search_query TEXT -- Hangi arama sorgusuyla bulunduğunu saklamak için (opsiyonel)
        )
        ''')
        conn.commit()
        conn.close()
        logging.info(f"'{DATABASE_NAME}' veritabanı hazır.")
    except sqlite3.Error as e:
        logging.error(f"Veritabanı kurulumunda hata: {e}")


def find_spotify_track_id(song_title, artist_name):
    """Verilen şarkı adı ve sanatçı ile Spotify'da arama yapıp track ID'sini bulur."""
    if not spotify_api:
        logging.error("Spotify API istemcisi mevcut değil.")
        return None

    query = f'track:"{song_title}" artist:"{artist_name}"'
    logging.info(f"Spotify'da aranıyor: {query}")
    try:
        # API Rate Limiting için küçük bir bekleme
        time.sleep(API_REQUEST_DELAY)
        results = spotify_api.search(q=query, type='track', limit=SPOTIFY_SEARCH_LIMIT)
        tracks = results.get('tracks', {}).get('items', [])

        if tracks:
            # En iyi eşleşmeyi al (genellikle ilk sonuç)
            best_match = tracks[0]
            found_id = best_match['id']
            found_title = best_match['name']
            found_artists = ", ".join([a['name'] for a in best_match['artists']])
            logging.info(f"Spotify eşleşmesi bulundu: ID: {found_id} - '{found_title}' by {found_artists}")
            # İsimlerin ne kadar benzediğini kontrol etmek isteyebilirsiniz (daha gelişmiş)
            return found_id
        else:
            logging.warning(f"'{song_title} - {artist_name}' için Spotify'da eşleşme bulunamadı.")
            return None
    except Exception as e:
        logging.error(f"Spotify araması sırasında hata ({query}): {e}")
        # Çok fazla istek hatası (429) alırsanız bekleme süresini artırın
        if "429" in str(e):
             logging.warning("Spotify API rate limitine takılmış olabilir. Bekleme süresi artırılıyor.")
             time.sleep(5) # Daha uzun bekle
        return None

def get_spotify_track_info(track_id):
    """Verilen Spotify ID'si ile şarkı bilgilerini alır."""
    if not spotify_api:
        logging.error("Spotify API istemcisi mevcut değil.")
        return None
    if not track_id:
        logging.warning("Geçersiz Spotify track ID'si alındı.")
        return None

    try:
        # API Rate Limiting için küçük bir bekleme
        time.sleep(API_REQUEST_DELAY)
        track = spotify_api.track(track_id)

        if not track:
            logging.warning(f"Spotify ID '{track_id}' için şarkı detayı bulunamadı.")
            return None

        title = track['name']
        artists = ", ".join([artist['name'] for artist in track['artists']])
        duration_ms = track['duration_ms']
        album = track['album']['name']
        album_art_url = track['album']['images'][0]['url'] if track['album']['images'] else None

        logging.info(f"Spotify '{track_id}' detayları alındı: '{title}' - {artists}")
        return {
            'id': track_id,
            'title': title,
            'artist': artists,
            'duration_ms': duration_ms,
            'album': album,
            'album_art_url': album_art_url
        }
    except Exception as e:
        logging.error(f"Spotify'dan '{track_id}' detayı alınırken hata: {e}")
        if "429" in str(e):
             logging.warning("Spotify API rate limitine takılmış olabilir. Bekleme süresi artırılıyor.")
             time.sleep(5) # Daha uzun bekle
        return None

# --- (find_and_filter_youtube_video, download_audio_from_youtube, add_song_to_database fonksiyonları öncekiyle aynı) ---

def find_and_filter_youtube_video(track_info):
    """YouTube'da şarkıyı arar, filtreler ve uygun videoyu bulur."""
    # Önceki kodla aynı, değişiklik yok
    search_query = f"{track_info['title']} {track_info['artist']} official audio"
    spotify_duration_s = track_info['duration_ms'] / 1000.0

    ydl_opts_search = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': True,
        'default_search': 'ytsearch5',
        'noplaylist': True,
    }

    # İlk arama (official audio ile)
    logging.info(f"YouTube'da aranıyor (1. deneme): '{search_query}'")
    best_match_url = search_youtube_internal(ydl_opts_search, search_query, spotify_duration_s, track_info['title'])

    # Eğer ilk aramada bulunamazsa veya 'official video' içeriyorsa, ikinci arama (official audio olmadan)
    if not best_match_url or "official video" in FORBIDDEN_KEYWORDS and "official video" in best_match_url.get('title', '').lower():
         if not best_match_url:
              logging.info("'Official audio' ile sonuç bulunamadı.")
         else:
              logging.info("'Official video' bulundu, 'official audio' olmadan tekrar aranacak.")

         search_query_alt = f"{track_info['title']} {track_info['artist']}"
         logging.info(f"YouTube'da aranıyor (2. deneme): '{search_query_alt}'")
         best_match_url_alt = search_youtube_internal(ydl_opts_search, search_query_alt, spotify_duration_s, track_info['title'])

         # Eğer ikinci arama daha iyi bir sonuç verdiyse (veya ilk arama boşsa) onu kullan
         if best_match_url_alt:
               best_match_url = best_match_url_alt

    if best_match_url:
        logging.info(f"Uygun YouTube videosu bulundu: {best_match_url.get('title', '')} ({str(timedelta(seconds=int(best_match_url.get('duration',0))))}) - {best_match_url.get('url')}")
        return best_match_url.get('url')
    else:
        logging.warning("Arama sonuçlarında uygun YouTube videosu bulunamadı (süre veya başlık kriterleri karşılanmadı).")
        return None


def search_youtube_internal(ydl_opts, search_query, spotify_duration_s, spotify_title):
    """ Yardımcı fonksiyon: Belirli bir sorgu ile YouTube araması yapar ve filtreler """
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch5:{search_query}", download=False, ie_key='YoutubeSearch') # ie_key eklemek bazen yardımcı olur

        if not result or 'entries' not in result or not result['entries']:
            logging.warning(f"YouTube araması ('{search_query}') sonuç vermedi.")
            return None

        best_candidate = None

        for entry in result['entries']:
            video_title = entry.get('title', '').lower()
            video_url = entry.get('url')
            video_duration = entry.get('duration')

            if not video_url or video_duration is None: # duration 0 olabilir, None olmamalı
                logging.debug(f"URL veya süre eksik, atlanıyor: {video_url}")
                continue

            # 1. Süre Kontrolü
            duration_diff = abs(spotify_duration_s - video_duration)
            if duration_diff > DURATION_TOLERANCE_SECONDS:
                logging.debug(f"Süre farkı fazla ({duration_diff:.2f}s > {DURATION_TOLERANCE_SECONDS}s), atlanıyor: {video_title} ({str(timedelta(seconds=int(video_duration)))})")
                continue

            # 2. Başlık Kontrolü (Yasaklı Kelimeler)
            is_forbidden = False
            for keyword in FORBIDDEN_KEYWORDS:
                if re.search(r'\b' + re.escape(keyword) + r'\b', video_title):
                    logging.debug(f"Yasaklı kelime '{keyword}' bulundu, atlanıyor: {video_title}")
                    is_forbidden = True
                    break
            if is_forbidden:
                continue

            # Eğer tüm kontrollerden geçerse, bu bir adaydır.
            # 'Official audio' içerenleri önceliklendirebiliriz.
            if best_candidate is None:
                best_candidate = entry # İlk uygun olanı al
            # Eğer mevcut aday 'official audio' içermiyorsa ve yeni bulunan içeriyorsa, yeniyi seç
            elif 'official audio' in video_title and 'official audio' not in best_candidate.get('title','').lower():
                 logging.debug(f"'Official audio' içeren daha iyi aday bulundu: {video_title}")
                 best_candidate = entry
            # Eğer her ikisi de 'official audio' içermiyorsa veya her ikisi de içeriyorsa,
            # başlığı Spotify başlığına daha çok benzeyeni seçebiliriz (opsiyonel, basitlik için şimdilik ilkini tutuyoruz)

        return best_candidate # En iyi adayı (veya None) döndür

    except Exception as e:
        logging.error(f"YouTube araması sırasında hata ('{search_query}'): {e}")
        return None


def download_audio_from_youtube(youtube_url, track_info):
    """Verilen YouTube URL'sinden sesi indirir."""
    # Önceki kodla aynı, değişiklik yok
    safe_title = re.sub(r'[\\/*?:"<>|]', "", track_info['title'])
    safe_artist = re.sub(r'[\\/*?:"<>|]', "", track_info['artist'])
    output_filename = f"{safe_artist} - {safe_title}.%(ext)s"
    output_path_template = os.path.join(DOWNLOAD_FOLDER, output_filename)

    ydl_opts_download = {
        'format': 'bestaudio/best',
        'outtmpl': output_path_template,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': False,
        'noplaylist': True,
        'noprogress': True, # İlerleme çubuğunu kapatabiliriz (çok fazla log olmaması için)
        'ffmpeg_location': None,
        'retries': 3, # İndirme hatası olursa tekrar dene
        'fragment_retries': 3
    }

    try:
        logging.info(f"İndiriliyor: {track_info['title']} - {track_info['artist']} ({youtube_url})")
        with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=True)
            # İndirilen dosyanın adını ve yolunu al (ffmpeg sonrası uzantıyı düzelt)
            base_name = ydl.prepare_filename(info_dict).rsplit('.', 1)[0]
            downloaded_file_path = base_name + '.' + ydl_opts_download['postprocessors'][0]['preferredcodec']

        if os.path.exists(downloaded_file_path):
             logging.info(f"Şarkı başarıyla indirildi: {downloaded_file_path}")
             return downloaded_file_path
        else:
             logging.error(f"İndirme sonrası dosya bulunamadı: {downloaded_file_path}. İndirme başarısız olmuş olabilir.")
             # Belki dosya adı farklıdır? Klasörü tarayabiliriz ama şimdilik None dönelim.
             return None

    except yt_dlp.utils.DownloadError as e:
         logging.error(f"YouTube'dan ses indirilirken İNDİRME HATASI ({track_info['title']}): {e}")
         return None
    except Exception as e:
        logging.error(f"YouTube'dan ses indirilirken genel HATA ({track_info['title']}): {e}")
        return None


def add_song_to_database(track_info, youtube_url, downloaded_file_path, search_query_used):
    """Şarkı bilgilerini veritabanına ekler."""
    # Önceki kodla aynı, search_query_used eklendi
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO songs (spotify_id, title, artist, album, spotify_duration_ms, youtube_url, downloaded_file_path, album_art_url, search_query)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(spotify_id) DO UPDATE SET
            youtube_url=excluded.youtube_url,
            downloaded_file_path=excluded.downloaded_file_path,
            album_art_url=excluded.album_art_url,
            -- Diğer alanları da güncelleyebilirsiniz, örn. başlık/sanatçı değiştiyse
            title=excluded.title,
            artist=excluded.artist,
            album=excluded.album,
            spotify_duration_ms=excluded.spotify_duration_ms,
            search_query=excluded.search_query

        ''', (
            track_info['id'],
            track_info['title'],
            track_info['artist'],
            track_info['album'],
            track_info['duration_ms'],
            youtube_url,
            downloaded_file_path,
            track_info['album_art_url'],
            search_query_used # Hangi arama sorgusuyla bulunduğu
        ))
        conn.commit()
        conn.close()
        logging.info(f"'{track_info['title']}' veritabanına eklendi/güncellendi.")
        return True
    except sqlite3.Error as e:
        logging.error(f"Veritabanına eklenirken hata: {e}")
        if conn:
            conn.close()
        return False

# --- Ana İşlem Akışı ---
if __name__ == "__main__":
    if not spotify_api:
        logging.critical("Spotify API başlatılamadı. İşlem durduruluyor.")
        exit() # Spotify API olmadan devam edilemez

    setup_database()

    # Şarkı listesi dosyasını kontrol et
    if not os.path.exists(SONG_LIST_FILE):
        logging.critical(f"Şarkı listesi dosyası bulunamadı: {SONG_LIST_FILE}")
        logging.critical(f"Lütfen her satırda 'Şarkı Adı - Sanatçı Adı' formatında şarkıları içeren bu dosyayı oluşturun.")
        exit()

    processed_count = 0
    downloaded_count = 0
    failed_spotify_search = 0
    failed_Youtube = 0
    failed_download = 0
    already_exists = 0

    # Şarkı listesini oku
    with open(SONG_LIST_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    logging.info(f"'{SONG_LIST_FILE}' dosyasından {len(lines)} şarkı okunuyor...")

    # Her şarkı için işlemleri yap
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or '-' not in line:
            logging.warning(f"Satır {i+1} geçersiz formatta, atlanıyor: '{line}'")
            continue

        # Satırı şarkı adı ve sanatçı olarak ayır
        parts = line.split('-', 1) # Sadece ilk tireye göre ayır
        song_title = parts[0].strip()
        artist_name = parts[1].strip()

        logging.info(f"\n--- İşleniyor ({i+1}/{len(lines)}): '{song_title}' - '{artist_name}' ---")
        processed_count += 1
        original_search_query = f"{song_title} - {artist_name}" # Loglama için sakla

        # 1. Spotify'da Şarkıyı Bul ve ID'sini Al
        spotify_id = find_spotify_track_id(song_title, artist_name)

        if not spotify_id:
            failed_spotify_search += 1
            continue # ID bulunamazsa sonraki şarkıya geç

        # 2. Spotify'dan Detaylı Bilgileri Al
        spotify_info = get_spotify_track_info(spotify_id)

        if not spotify_info:
            # ID bulundu ama detay alınamadıysa bu garip bir durum, yine de devam etme
            logging.error(f"Spotify ID '{spotify_id}' için detay alınamadı.")
            continue

        # 3. Veritabanında Kontrol Et (İndirilmiş mi?)
        try:
             conn_check = sqlite3.connect(DATABASE_NAME)
             cursor_check = conn_check.cursor()
             cursor_check.execute("SELECT downloaded_file_path FROM songs WHERE spotify_id = ?", (spotify_id,))
             existing_entry = cursor_check.fetchone()
             conn_check.close()

             if existing_entry and existing_entry[0] and os.path.exists(existing_entry[0]):
                 logging.info(f"'{spotify_info['title']}' zaten indirilmiş ve veritabanında mevcut: {existing_entry[0]}")
                 already_exists += 1
                 continue # Zaten varsa sonraki şarkıya geç
             elif existing_entry:
                  logging.warning(f"'{spotify_info['title']}' veritabanında var ama dosya ({existing_entry[0]}) bulunamadı. Tekrar indirilecek.")
        except sqlite3.Error as e:
             logging.error(f"Veritabanı kontrolü sırasında hata: {e}")
             # Hata olsa bile devam etmeyi deneyebiliriz

        # 4. YouTube'da Uygun Videoyu Bul
        youtube_match_url = find_and_filter_youtube_video(spotify_info)

        if not youtube_match_url:
            failed_Youtube += 1
            continue # Uygun video yoksa sonraki şarkıya geç

        # 5. YouTube'dan Sesi İndir
        downloaded_path = download_audio_from_youtube(youtube_match_url, spotify_info)

        if not downloaded_path:
            failed_download += 1
            continue # İndirme başarısızsa sonraki şarkıya geç

        # 6. Veritabanına Ekle/Güncelle
        if add_song_to_database(spotify_info, youtube_match_url, downloaded_path, original_search_query):
             downloaded_count += 1
        else:
             # Veritabanı hatası olsa bile dosya indi, ama loglandı
             failed_download += 1 # Veritabanı hatasını da indirme hatası sayabiliriz

    # İşlem Sonu Özet
    logging.info("\n--- İşlem Tamamlandı Özet ---")
    logging.info(f"Toplam İşlenen Şarkı (Listeden): {processed_count}")
    logging.info(f"Başarıyla İndirilen / Eklenen: {downloaded_count}")
    logging.info(f"Zaten Mevcut Olan (Atlandı): {already_exists}")
    logging.info(f"Spotify ID Bulunamayan: {failed_spotify_search}")
    logging.info(f"Uygun YouTube Videosu Bulunamayan: {failed_Youtube}")
    logging.info(f"İndirme veya Veritabanı Hatası: {failed_download}")
    logging.info(f"İndirilen şarkılar '{DOWNLOAD_FOLDER}' klasöründe.")
    logging.info(f"Veritabanı dosyası: '{DATABASE_NAME}'")