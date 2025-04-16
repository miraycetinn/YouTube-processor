# youtube_processor.py
import sys
import yt_dlp
import os
import re
import logging
import argparse
from datetime import timedelta
import json # Sonucu yapılandırılmış JSON olarak basmak için

# --- Yapılandırma (Gerekli olanları tut) ---
DURATION_TOLERANCE_SECONDS = 10 # Saniye cinsinden tolerans
FORBIDDEN_KEYWORDS = [
    "cover", "remix", "live", "acoustic", "instrumental", "lyrics",
    "parody", "tutorial", "reaction", "karaoke", "mashup", "canlı",
    "akustik", "enstrümantal", "sözleri", "parodi", "ders", "tepki",
    "konser", "remiks"
]
# ---

# Loglamayı ayarla (stderr'e yazacak şekilde)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - YT_PROC - %(levelname)s - %(message)s', stream=sys.stderr)

# --- YouTube Arama/Filtreleme Fonksiyonları (Önceki koddan kopyalanacak) ---
# search_youtube_internal ve find_and_filter_youtube_video fonksiyonlarını
# buraya yapıştırın. find_and_filter_youtube_video sadece URL döndürmeli.

def search_youtube_internal(ydl_opts, search_query, spotify_duration_s, spotify_title):
    """ Yardımcı fonksiyon: Belirli bir sorgu ile YouTube araması yapar ve filtreler """
    try:
        logging.info(f"YouTube'da aranıyor: '{search_query}'")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # extract_info içinde ie_key belirtmek bazen arama için daha iyi çalışır
            result = ydl.extract_info(f"ytsearch5:{search_query}", download=False, ie_key='YoutubeSearch')

        if not result or 'entries' not in result or not result['entries']:
            logging.warning(f"YouTube araması ('{search_query}') sonuç vermedi.")
            return None

        best_candidate = None
        min_duration_diff = float('inf') # En düşük süre farkını tutalım

        for entry in result['entries']:
            video_title = entry.get('title', '').lower()
            video_url = entry.get('url')
            video_duration = entry.get('duration') # saniye cinsinden

            if not video_url or video_duration is None:
                logging.debug(f"URL veya süre eksik, atlanıyor: {video_url}")
                continue

            # 1. Başlık Kontrolü (Yasaklı Kelimeler) - Önce yapalım
            is_forbidden = False
            for keyword in FORBIDDEN_KEYWORDS:
                # Kelimenin tek başına veya boşluk/özel karakterle çevrili olup olmadığını kontrol et
                if re.search(r'\b' + re.escape(keyword) + r'\b', video_title):
                    logging.debug(f"Yasaklı kelime '{keyword}' bulundu, atlanıyor: {video_title}")
                    is_forbidden = True
                    break
            if is_forbidden:
                continue

            # 2. Süre Kontrolü
            duration_diff = abs(spotify_duration_s - video_duration)
            if duration_diff > DURATION_TOLERANCE_SECONDS:
                logging.debug(f"Süre farkı fazla ({duration_diff:.2f}s > {DURATION_TOLERANCE_SECONDS}s), atlanıyor: {video_title} ({str(timedelta(seconds=int(video_duration)))})")
                continue

            # Eğer tüm kontrollerden geçerse, bu bir adaydır.
            # Daha iyi bir aday bulduk mu diye kontrol edelim:
            # - Mevcut en iyi aday yoksa, bunu al.
            # - Veya yeni adayın süre farkı daha düşükse, bunu al.
            # - Veya süre farkları aynıysa ve yeni aday 'official audio' içerirken eskisi içermiyorsa, yeniyi al.
            if best_candidate is None or duration_diff < min_duration_diff:
                 logging.debug(f"Daha iyi aday bulundu (süre farkı {duration_diff:.2f}s): {video_title}")
                 best_candidate = entry
                 min_duration_diff = duration_diff
            elif duration_diff == min_duration_diff and 'official audio' in video_title and 'official audio' not in best_candidate.get('title','').lower():
                 logging.debug(f"'Official audio' içeren eş süreli aday bulundu: {video_title}")
                 best_candidate = entry
                 # min_duration_diff aynı kalır

        if best_candidate:
             logging.info(f"En iyi aday seçildi: {best_candidate.get('title','')} ({str(timedelta(seconds=int(best_candidate.get('duration',0))))}) - Fark: {min_duration_diff:.2f}s")
        else:
             logging.warning(f"'{search_query}' için kriterlere uygun aday bulunamadı.")


        return best_candidate # En iyi adayı (veya None) döndür

    except Exception as e:
        logging.error(f"YouTube araması sırasında hata ('{search_query}'): {e}")
        return None


def find_and_filter_youtube_video(track_info):
    """YouTube'da şarkıyı arar, filtreler ve uygun video URL'sini bulur."""
    # Spotify bilgilerini al
    track_title = track_info['title']
    track_artist = track_info['artist']
    spotify_duration_s = track_info['duration_ms'] / 1000.0

    # yt-dlp arama ayarları
    ydl_opts_search = {
        'quiet': True,
        'extract_flat': 'discard_in_playlist', # Daha fazla metadata alabilmek için sadece liste değil
        'force_generic_extractor': False, # Generic extractor'ı zorlama, YouTube'un kendi extractor'ını kullansın
        'noplaylist': True,
        'noprogress': True,
        'skip_download': True, # Sadece bilgi al, indirme
        'writesinglejson': False, # JSON dosyası yazma
        'logtostderr': False # Logları stderr'e yt-dlp kendisi basmasın, biz logging ile basıyoruz
    }

    # 1. Arama: "Official Audio" ile
    search_query_audio = f"{track_title} {track_artist} official audio"
    best_match_audio = search_youtube_internal(ydl_opts_search, search_query_audio, spotify_duration_s, track_title)

    # 2. Arama: Sadece isim ve sanatçı ile
    search_query_base = f"{track_title} {track_artist}"
    best_match_base = search_youtube_internal(ydl_opts_search, search_query_base, spotify_duration_s, track_title)

    # Seçim Mantığı:
    # - Eğer "official audio" araması sonuç verdiyse ve "base" arama sonuç vermediyse, audio'yu kullan.
    # - Eğer "base" arama sonuç verdiyse ve "audio" arama sonuç vermediyse, base'i kullan.
    # - Eğer ikisi de sonuç verdiyse:
    #   - Süre farkı daha düşük olanı tercih et.
    #   - Süre farkları çok yakınsa (örn < 1 sn), "official audio" başlığı içerenini tercih et.
    # - Eğer ikisi de sonuç vermediyse, None döndür.

    final_match = None
    if best_match_audio and not best_match_base:
        final_match = best_match_audio
    elif best_match_base and not best_match_audio:
        final_match = best_match_base
    elif best_match_audio and best_match_base:
        diff_audio = abs(spotify_duration_s - best_match_audio.get('duration', float('inf')))
        diff_base = abs(spotify_duration_s - best_match_base.get('duration', float('inf')))

        if diff_audio < diff_base - 0.5: # Süre farkı bariz daha iyiyse audio'yu seç (0.5 sn tolerans)
            final_match = best_match_audio
        elif diff_base < diff_audio - 0.5: # Süre farkı bariz daha iyiyse base'i seç
            final_match = best_match_base
        else: # Süre farkları yakınsa
            if 'official audio' in best_match_audio.get('title','').lower():
                 final_match = best_match_audio # Audio içeren öncelikli
            else:
                 final_match = best_match_base # Yoksa base'i seç

    if final_match:
        logging.info(f"Sonuç olarak seçilen YouTube videosu: {final_match.get('title', '')} URL: {final_match.get('url')}")
        return final_match.get('url') # Sadece URL'yi döndür
    else:
        logging.warning("Her iki YouTube aramasında da uygun sonuç bulunamadı.")
        return None


# --- YouTube İndirme Fonksiyonu (Önceki koddan uyarlanacak) ---
def download_audio_from_youtube(youtube_url, output_dir, output_filename_base):
    """ Verilen URL'den sesi indirir ve belirtilen dosya adına kaydeder. """
    output_path_template = os.path.join(output_dir, f"{output_filename_base}.%(ext)s")
    final_expected_codec = 'mp3' # Hedef format

    ydl_opts_download = {
        'format': 'bestaudio/best',
        'outtmpl': output_path_template,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': final_expected_codec,
            'preferredquality': '192', # Veya istediğiniz kalite
        }],
        'quiet': True, # Daha az çıktı versin
        'noplaylist': True,
        'noprogress': True,
        'ffmpeg_location': None, # Sistemdeki FFmpeg'i bulsun
        'retries': 3,
        'fragment_retries': 3,
        'logtostderr': False # Logları biz yönetiyoruz
    }

    final_file_path = None
    try:
        logging.info(f"İndiriliyor: {youtube_url} -> {output_path_template}")
        with yt_dlp.YoutubeDL(ydl_opts_download) as ydl:
            info_dict = ydl.extract_info(youtube_url, download=True)
            # İndirme sonrası dosya adını ve yolunu al (codec/uzantı değişebilir)
            # yt-dlp'nin prepare_filename'i bazen ffmpeg sonrası adı vermez, manuel oluşturalım
            final_file_path = os.path.join(output_dir, f"{output_filename_base}.{final_expected_codec}")

        if os.path.exists(final_file_path):
             logging.info(f"Şarkı başarıyla indirildi ve dönüştürüldü: {final_file_path}")
             return final_file_path
        else:
             # Bazen ffmpeg sonrası ad farklı olabilir, tam şablonla kontrol et
             # (Bu kısım karmaşıklaşabilir, şimdilik basit kontrol yeterli)
             logging.error(f"İndirme sonrası dosya beklenen yolda bulunamadı: {final_file_path}")
             # Klasördeki mp3 dosyasını aramayı deneyebiliriz ama riskli olabilir
             return None

    except yt_dlp.utils.DownloadError as e:
         logging.error(f"YouTube'dan ses indirilirken İNDİRME HATASI: {e}")
         return None
    except Exception as e:
        # İndirme sırasında video bulunamadı vb. hataları yakala
        logging.error(f"YouTube'dan ses indirilirken genel HATA: {e}")
        return None


# --- Ana Çalıştırma Bloğu ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Find, filter, and download YouTube audio matching Spotify track info.')
    parser.add_argument('--track-name', required=True, help='Spotify track name')
    parser.add_argument('--artist-name', required=True, help='Spotify artist name(s)')
    parser.add_argument('--duration-ms', required=True, type=int, help='Spotify track duration in milliseconds')
    parser.add_argument('--output-dir', required=True, help='Directory to save the downloaded file')
    parser.add_argument('--output-filename-base', required=True, help='Base filename (without extension) for the downloaded mp3 (e.g., spotify_track_id)')

    args = parser.parse_args()

    # Gerekli klasörün var olduğundan emin ol
    os.makedirs(args.output_dir, exist_ok=True)

    # Fonksiyonların kullanacağı track_info sözlüğünü oluştur
    track_info_sim = {
        'title': args.track_name,
        'artist': args.artist_name,
        'duration_ms': args.duration_ms
    }

    # 1. Adım: Uygun YouTube Videosunu Bul
    youtube_match_url = find_and_filter_youtube_video(track_info_sim)

    if not youtube_match_url:
        error_message = "No suitable YouTube video found matching criteria."
        logging.error(error_message)
        # Başarısızlık durumunda stderr'e JSON formatında hata bas
        print(json.dumps({"success": False, "error": error_message}), file=sys.stderr)
        sys.exit(1) # Hata koduyla çık

    # 2. Adım: Sesi İndir
    downloaded_path = download_audio_from_youtube(
        youtube_match_url,
        args.output_dir,
        args.output_filename_base
    )

    if not downloaded_path:
        error_message = "Failed to download audio from YouTube."
        logging.error(error_message)
        # Başarısızlık durumunda stderr'e JSON formatında hata bas
        print(json.dumps({"success": False, "error": error_message}), file=sys.stderr)
        sys.exit(1) # Hata koduyla çık

    # 3. Adım: Başarı Durumu
    # Başarılı olursa, stdout'a JSON formatında sonucu bas
    result = {
        "success": True,
        "downloaded_file_path": downloaded_path,
        "youtube_url": youtube_match_url # Bulunan YouTube URL'sini de döndür
    }
    print(json.dumps(result))
    sys.exit(0) # Başarı koduyla çık