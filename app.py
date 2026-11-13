"""Start CertiKeep:  python app.py   then open http://127.0.0.1:8000"""
import os

from certikeep import create_app

app = create_app()

if __name__ == "__main__":
    # Port 8000, not 5000: on macOS, port 5000 is taken by AirPlay Receiver.
    port = int(os.environ.get("PORT", 8000))
    print(f"\n  CertiKeep is running: open http://127.0.0.1:{port} in your browser (Ctrl+C to stop)\n")
    app.run(host="127.0.0.1", port=port, debug=False)
