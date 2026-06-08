from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is running!'

def keep_alive():
    def run():
        app.run(host='0.0.0.0', port=8080)
    t = threading.Thread(target=run, daemon=True)
    t.start()