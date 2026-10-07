# JamCam

Monitors live TfL traffic cameras near a location and saves the footage as MP4. Set a pin on the map and any cameras within your chosen radius will automatically record. Clear the pin to stop and save.

---

## Prerequisites

- Python 3.8 or newer — https://www.python.org/downloads
- Git — https://git-scm.com/downloads

---

## Installation

Clone the repo and install dependencies:

```
git clone https://github.com/HadenHenke/jamcam.git
cd jamcam
pip install -r requirements.txt
```

Copy the example config:

```
cp config.example.py config.py
```

Open `config.py` and change anything you need — by default it runs on port 8080 and saves recordings to a `recordings/` folder in the project directory.

---

## Running locally

```
python app.py
```

Open `http://localhost:8080` in your browser. Click anywhere on the map to set a location — cameras within the radius will start recording immediately. Adjust the slider to change the radius. Click **clear location** to stop recording and save the footage.

Recordings are saved to `recordings/` with a timestamped subfolder per session. If a camera captured multiple clips they are automatically joined into a single MP4.

---

## Accessing from your phone

Because geolocation in the browser requires HTTPS, you need a secure tunnel from your laptop to your phone. This uses [ngrok](https://ngrok.com), which is free.

**On your laptop:**

1. Make sure the app is not already running
2. Double-click `start.bat`

On first run it will:
- Install ngrok automatically via winget
- Ask you to create a free account at https://dashboard.ngrok.com/signup and paste your authtoken — this is a one-time step, ngrok saves it for future runs
- Start the camera server
- Start the ngrok tunnel
- Print an `https://` URL in the console, for example:
  ```
  https://abc123.ngrok-free.app
  ```

3. Open that URL in Safari on your iPhone
4. Tap **⦿ Use real location** and allow location access when prompted

The app will then track your GPS position and record any cameras you walk x distance form. When you're done, tap **clear location** — the footage saves to the `recordings/` folder on your laptop.

> The ngrok URL changes each time you run `start.bat`. If you want a fixed URL, you can set a free static domain in the ngrok dashboard.
