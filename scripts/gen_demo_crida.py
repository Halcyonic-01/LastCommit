import urllib.request
import json

def generate(text, lang, filename):
    url = "http://localhost:8765/synthesize"
    data = json.dumps({"text": text, "lang": lang}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as response:
            with open(filename, "wb") as f:
                f.write(response.read())
        print(f"Saved {filename}")
    except Exception as e:
        print(f"Failed: {e}")

generate("ಮಣ್ಣಿನ ತೇವ ಉಳಿಸಿ, ಈ ವಾರ ಮಳೆಯ ಅಗತ್ಯವಿರುವ ಕೆಲಸ ಮುಂದೂಡಿ.", "kn", "web/public/demo_crida.wav")
