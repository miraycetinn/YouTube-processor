// test_node_integration.js - BAĞIMSIZ TEST SCRIPT'İ

// Gerekli Node.js modüllerini import et
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

console.log("Node.js Integration Test Script Starting...");
console.log("==========================================");

// --- Test Girdileri ---
// Normalde bu bilgiler MongoDB ve Spotify API'sinden gelir.
// Burada testi yapabilmek için manuel olarak tanımlıyoruz.
const testSpotifyInfo = {
    trackId: '0VjIjW4GlUZAMYd2vXMi3b',      // Örnek Spotify ID (Tarkan - Şımarık)
    trackName: 'Şımarık',                  // Örnek Şarkı Adı
    artistNameForSearch: 'Tarkan',         // Python'a gönderilecek sanatçı adı (arama için)
    spotifyDurationMs: 235533              // Örnek Süre (milisaniye)
};
// --- Test Girdileri Sonu ---

// --- Ayarlar ---
const isWindows = process.platform === "win32";
const venvPath = 'venv'; // Kullandığınız venv klasör adı
const venvPythonExecutable = isWindows
    ? path.join(__dirname, venvPath, 'Scripts', 'python.exe')
    : path.join(__dirname, venvPath, 'bin', 'python3'); // macOS/Linux için python3 kullandığımızı varsayalım
const pythonCommand = venvPythonExecutable;
const pythonScriptPath = path.join(__dirname, 'youtube_processor.py'); // Python script'inin yolu
const tempDownloadDir = path.join(__dirname, 'temp_node_test'); // Test için geçici klasör
const outputFilenameBase = testSpotifyInfo.trackId;
// --- Ayarlar Sonu ---

// Ana test fonksiyonu
async function runTest() {
    console.log(`Testing with: ${testSpotifyInfo.artistNameForSearch} - ${testSpotifyInfo.trackName}`);
    console.log(`Output directory: ${tempDownloadDir}`);
    console.log(`Output base filename: ${outputFilenameBase}`);
    console.log(`Python script path: ${pythonScriptPath}`);
    console.log(`Using Python command: ${pythonCommand}`); // Hangi python'u kullandığını logla

    // --- 1. Geçici İndirme Klasörünü Oluştur ---
    try {
        if (!fs.existsSync(tempDownloadDir)){
            console.log(`Creating temporary directory: ${tempDownloadDir}`);
            fs.mkdirSync(tempDownloadDir, { recursive: true });
        } else {
            console.log(`Temporary directory already exists: ${tempDownloadDir}`);
        }
    } catch (err) {
        console.error(`Error creating temporary directory "${tempDownloadDir}":`, err);
        console.log("Test Failed.");
        return;
    }

    // --- 2. Python Script'ini Çağır ---
    const pythonPromise = new Promise((resolve, reject) => {
        const args = [
            pythonScriptPath,
            '--track-name', testSpotifyInfo.trackName,
            '--artist-name', testSpotifyInfo.artistNameForSearch,
            '--duration-ms', testSpotifyInfo.spotifyDurationMs.toString(),
            '--output-dir', tempDownloadDir,
            '--output-filename-base', outputFilenameBase
        ];
        console.log(`Spawning command: ${pythonCommand} ${args.map(a => a.includes(' ') ? `"${a}"` : a).join(' ')}`);

        const pythonProcess = spawn(pythonCommand, args);
        let scriptOutput = '';
        let scriptError = '';

        pythonProcess.stdout.on('data', (data) => { scriptOutput += data.toString(); });
        pythonProcess.stderr.on('data', (data) => { scriptError += data.toString(); console.error(`Python stderr chunk: ${data.toString()}`); });
        pythonProcess.on('close', (code) => {
             console.log(`Python script process exited with code ${code}`);
              if (scriptError.trim().length > 0) { console.error(`Python script full stderr output:\n---\n${scriptError}\n---`);}
            if (code === 0) {
                try {
                    const result = JSON.parse(scriptOutput.trim());
                    if (result.success && result.downloaded_file_path) {
                        if (fs.existsSync(result.downloaded_file_path)) { resolve(result); }
                        else { reject(new Error(`Python reported success but output file missing: ${result.downloaded_file_path}`)); }
                    } else { reject(new Error(result.error || 'Python script failed internally (success:false).')); }
                } catch (parseError) { reject(new Error('Failed to parse Python script JSON output.')); }
            } else { reject(new Error(scriptError.trim() || `Python script exited with error code ${code}.`)); }
        });
        pythonProcess.on('error', (err) => { reject(new Error(`Failed to start Python subprocess: ${err.message}`)); });
    });

    // --- 3. Sonucu İşle ---
    let downloadedFilePath = null;
    try {
        console.log("Waiting for Python script to complete...");
        const pythonResult = await pythonPromise;

        console.log("--- Python Script Call SUCCESS ---");
        console.log("Received Result:", pythonResult);
        downloadedFilePath = pythonResult.downloaded_file_path;
        console.log(`Verified Downloaded File Path: ${downloadedFilePath}`);
        console.log(`Found YouTube URL: ${pythonResult.youtube_url}`);
        console.log("\nTest Passed!");

    } catch (pyError) {
        console.error("--- Python Script Call FAILED ---");
        console.error("Error:", pyError.message);
        console.log("\nTest Failed.");
    } finally {
        // --- 4. Temizlik ---
        if (downloadedFilePath && fs.existsSync(downloadedFilePath)) {
            try {
                fs.unlinkSync(downloadedFilePath);
                console.log(`Cleaned up temporary file: ${downloadedFilePath}`);
            } catch (cleanupError) {
                console.error(`Error cleaning up file "${downloadedFilePath}":`, cleanupError);
            }
        }
        console.log("==========================================");
        console.log("Test Script Finished.");
    }
}

// Testi başlat
runTest();