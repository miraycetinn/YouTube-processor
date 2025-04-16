# 1. Temel İmaj: Node.js'in LTS (Uzun Süreli Destek) versiyonunu içeren Debian tabanlı bir imaj seçelim.
FROM node:20-bookworm-slim
# Veya projenizin kullandığı Node.js sürümüne uygun bir imaj seçin.

# 2. Çalışma Dizini Ayarla
WORKDIR /usr/src/app

# 3. Sistem Bağımlılıklarını Kur: Python3, PIP ve FFmpeg
# Node.js imajında bunlar genellikle bulunmaz, bizim kurmamız gerekir.
# Tek RUN komutunda yaparak katman sayısını azaltıyoruz.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 4. Python Gereksinimlerini Kur
# Önce sadece gereksinim dosyasını kopyala (Docker cache optimizasyonu)
COPY requirements.txt ./
# pip kullanarak Python kütüphanelerini (yt-dlp) kur
RUN pip3 install --no-cache-dir -r requirements.txt

# 5. Python Yardımcı Script'ini Kopyala
COPY youtube_processor.py ./

# 6. Node.js Uygulama Bağımlılıklarını Kur
# Önce package*.json dosyalarını kopyala (Docker cache optimizasyonu)
COPY package*.json ./
# npm install yerine 'npm ci' kullanmak genellikle production build'leri için daha iyidir.
# Sadece production bağımlılıklarını kurar.
RUN npm ci --only=production

# 7. Node.js Uygulama Kodunu Kopyala
# Geri kalan tüm uygulama kodunu kopyala (.dockerignore ile hariç tutulanlar dışında)
COPY . .

# 8. Ortam Değişkenleri (Örnek - .env yerine bunları kullanın)
# ENV NODE_ENV=production
# ENV SPOTIPY_CLIENT_ID=${SPOTIPY_CLIENT_ID} # Build sırasında veya run sırasında verilebilir
# ENV SPOTIPY_CLIENT_SECRET=${SPOTIPY_CLIENT_SECRET}
# ENV MONGO_URI=${MONGO_URI}
# ENV MINIO_ENDPOINT=${MINIO_ENDPOINT}
# ... diğer gerekli ortam değişkenleri ...

# 9. Uygulamanın Çalışacağı Port (Eğer bir web server ise)
# EXPOSE 3000

# 10. Konteyner Başladığında Çalıştırılacak Komut
# Ana Node.js uygulamanızın başlangıç dosyasını belirtin.
# Örneğin, server.js, app.js, index.js veya worker'ı başlatan script olabilir.
CMD [ "node", "test_node_integration.js" ]
# !!! YUKARIDAKİ "your_main_app_file.js" KISMINI KENDİ ANA UYGULAMA DOSYANIZIN ADIYLA DEĞİŞTİRİN !!!