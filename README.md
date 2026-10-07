# JamCam

Records live TfL traffic camera footage when you're nearby. Set a location on the map, and any cameras within range automatically download their video clips. Clear your location to stop and save.

## Requirements

- Python 3.8+
- Windows (for `start.bat`/ngrok launcher) or any OS for local use

## Setup

```
pip install -r requirements.txt
cp config.example.py config.py
```

Edit `config.py` if you want to change the port or recordings folder.

## Running locally

```
python app.py
```

Open `http://localhost:8080` in your browser.

## Running on your phone

Double-click `start.bat`. On first run it will:
1. Install ngrok if needed
2. Ask for your ngrok authtoken — get one free at https://dashboard.ngrok.com/signup
3. Print an `https://` URL to open on your phone

The authtoken is a one-time setup. ngrok stores it in its own config file — you don't need to add it anywhere in this project.

## Usage

1. Click anywhere on the map to set your location (or tap **Use real location** on the phone)
2. Adjust the radius slider — cameras within range start recording automatically
3. Tap **clear location** to stop recording and save

Recordings are saved to the `recordings/` folder (or the path set in `config.py`). Each session gets a timestamped subfolder. If multiple clips were captured for a camera they are concatenated into a single MP4.
