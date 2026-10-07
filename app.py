"""
TfL JamCam recorder — downloads the MP4 clips TfL already generates.
Run: python app.py  →  http://localhost:8080
"""

import json
import math
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import config

TFL_API = "https://api.tfl.gov.uk/Place/Type/JamCam"
PORT    = config.PORT
_here   = os.path.dirname(os.path.abspath(__file__))
REC_DIR = config.RECORDINGS_DIR or os.path.join(_here, "recordings")
POLL    = 5  # seconds between HEAD checks

os.makedirs(REC_DIR, exist_ok=True)


# ── TfL ───────────────────────────────────────────────────────────────────────

def fetch_cameras():
    req = urllib.request.Request(TFL_API, headers={"User-Agent": "JamCam/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    cams = []
    for place in data:
        props = {p["key"]: p["value"] for p in place.get("additionalProperties", [])}
        if not props.get("videoUrl"):
            continue
        cams.append({
            "id":    place.get("id", ""),
            "name":  place.get("commonName", "Unknown"),
            "lat":   place.get("lat", 0),
            "lon":   place.get("lon", 0),
            "image": props.get("imageUrl", ""),
            "video": props.get("videoUrl", ""),
        })
    return cams


def haversine(lat1, lon1, lat2, lon2):
    R, r = 6371, math.pi / 180
    a = math.sin((lat2-lat1)*r/2)**2 + math.cos(lat1*r)*math.cos(lat2*r)*math.sin((lon2-lon1)*r/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# ── Recording ─────────────────────────────────────────────────────────────────

def get_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def concat_clips(clips, out_path):
    ffmpeg = get_ffmpeg()
    if not ffmpeg:
        print("  imageio-ffmpeg not found — run: pip install imageio imageio-ffmpeg")
        return False
    list_path = out_path + ".txt"
    with open(list_path, "w") as f:
        for c in clips:
            f.write(f"file '{c.replace(os.sep, '/')}'\n")
    r = subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path],
        capture_output=True, timeout=60,
    )
    try: os.unlink(list_path)
    except OSError: pass
    return r.returncode == 0


class CameraRecorder:
    def __init__(self, cam, session_dir):
        self.cam   = cam
        self.dir   = os.path.join(session_dir, cam["id"].replace("/", "_"))
        self.clips = []
        self._stop = threading.Event()
        os.makedirs(self.dir, exist_ok=True)
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        url = self.cam["video"]
        last_modified = None
        n = 0
        while not self._stop.is_set():
            try:
                # cheap HEAD check first
                req = urllib.request.Request(url, method="HEAD",
                                             headers={"User-Agent": "JamCam/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    lm = r.headers.get("Last-Modified")

                if lm and lm != last_modified:
                    last_modified = lm
                    req2 = urllib.request.Request(url, headers={"User-Agent": "JamCam/1.0"})
                    with urllib.request.urlopen(req2, timeout=15) as r:
                        data = r.read()
                    path = os.path.join(self.dir, f"clip_{n:05d}.mp4")
                    with open(path, "wb") as f:
                        f.write(data)
                    self.clips.append(path)
                    n += 1
                    print(f"  [{self.cam['name']}] clip {n}  ({len(data)//1024} KB)")
            except Exception:
                pass
            self._stop.wait(POLL)

    def finalize(self):
        if not self.clips:
            print(f"  [{self.cam['name']}] no clips captured")
            return
        if len(self.clips) == 1:
            print(f"  Saved: {self.clips[0]}")
            return
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.cam["name"]).strip()
        out  = os.path.join(self.dir, f"{safe}.mp4")
        if concat_clips(self.clips, out):
            print(f"  Saved ({len(self.clips)} clips): {out}")
        else:
            print(f"  Clips saved individually in: {self.dir}")


class WatchState:
    def __init__(self):
        self.recorders = []
        self.lock = threading.Lock()

    def start(self, lat, lon, radius_km, cameras):
        self.stop()
        nearby = [c for c in cameras if haversine(lat, lon, c["lat"], c["lon"]) <= radius_km]
        if not nearby:
            return 0
        ts = time.strftime("%Y%m%d_%H%M%S")
        d  = os.path.join(REC_DIR, ts)
        os.makedirs(d, exist_ok=True)
        with self.lock:
            self.recorders = [CameraRecorder(c, d) for c in nearby]
        print(f"  Watching {len(self.recorders)} cameras within {radius_km*1000:.0f} m")
        return len(self.recorders)

    def stop(self):
        with self.lock:
            recs, self.recorders = list(self.recorders), []
        if not recs:
            return
        print(f"  Stopping {len(recs)} recorder(s)…")
        for rec in recs: rec.stop()
        for rec in recs: threading.Thread(target=rec.finalize, daemon=True).start()


WATCH = WatchState()


# ── HTTP ──────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    cameras = None

    def log_message(self, *a): pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))

    def do_GET(self):
        if Handler.cameras is None:
            try:
                Handler.cameras = fetch_cameras()
            except Exception as e:
                print(f"  Fetch failed: {e}")
                Handler.cameras = []
        self.send_html(PAGE.replace("__CAMS__", json.dumps(Handler.cameras)))

    def do_POST(self):
        b = self.body()
        if self.path == "/watch":
            n = WATCH.start(float(b["lat"]), float(b["lon"]),
                            float(b.get("r", 0.25)), Handler.cameras or [])
            self.send_json({"n": n})
        elif self.path == "/unwatch":
            WATCH.stop()
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "unknown"}, 404)


# ── Page ──────────────────────────────────────────────────────────────────────

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JamCam</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css">
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%;font-family:system-ui,sans-serif;background:#111;overflow:hidden}
  #map{position:absolute;inset:0}

  #hud{position:absolute;top:12px;left:12px;z-index:1000;display:flex;flex-direction:column;gap:6px;pointer-events:none}
  #title{background:rgba(10,10,20,.88);backdrop-filter:blur(6px);color:#e53935;font-size:.85rem;font-weight:700;padding:5px 10px;border-radius:6px;border:1px solid #333;letter-spacing:.04em}
  #badge{display:none;align-items:center;gap:6px;background:rgba(10,25,10,.92);backdrop-filter:blur(6px);border:1px solid #2e7d32;border-radius:6px;padding:5px 10px;font-size:.78rem;color:#a5d6a7}
  #badge.on{display:flex}
  .pulse{width:7px;height:7px;border-radius:50%;background:#e53935;animation:blink 1s infinite;flex-shrink:0}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}

  #ctrl{position:absolute;bottom:28px;left:12px;z-index:1000;display:none;flex-direction:column;gap:8px;background:rgba(10,10,20,.9);backdrop-filter:blur(6px);border:1px solid #333;border-radius:8px;padding:10px 14px;min-width:200px}
  #ctrl.on{display:flex}
  #rrow{display:flex;align-items:center;gap:8px}
  #rslider{flex:1;accent-color:#e53935;cursor:pointer}
  #rval{font-size:.75rem;color:#e53935;font-weight:600;min-width:46px;text-align:right}
  #clrbtn{font-size:.75rem;color:#666;background:transparent;border:none;cursor:pointer;align-self:flex-end;padding:0}
  #clrbtn:hover{color:#ccc}

  #geobtn{position:absolute;bottom:28px;right:12px;z-index:1000;background:rgba(10,10,20,.9);backdrop-filter:blur(6px);border:1px solid #333;border-radius:8px;padding:7px 12px;color:#777;font-size:.75rem;cursor:pointer}
  #geobtn:hover{color:#ccc;border-color:#555}
  #geobtn.on{color:#1976d2;border-color:#1976d2}

  #tip{position:absolute;bottom:28px;left:50%;transform:translateX(-50%);z-index:1000;pointer-events:none;background:rgba(10,10,20,.82);backdrop-filter:blur(4px);color:#555;font-size:.75rem;padding:5px 12px;border-radius:20px;border:1px solid #222;white-space:nowrap}

  .cdot{width:8px;height:8px;border-radius:50%;background:#e53935;border:1.5px solid rgba(255,255,255,.7);transition:opacity .4s}
  .ldot{width:16px;height:16px;border-radius:50%;background:#1976d2;border:3px solid #fff;box-shadow:0 0 0 4px rgba(25,118,210,.3);animation:lp 2s infinite}
  @keyframes lp{0%,100%{box-shadow:0 0 0 4px rgba(25,118,210,.3)}50%{box-shadow:0 0 0 9px rgba(25,118,210,.07)}}

  .leaflet-popup-content-wrapper{background:#1a1a1a!important;color:#ddd!important;border:1px solid #333!important;border-radius:8px!important;box-shadow:0 4px 20px rgba(0,0,0,.7)!important}
  .leaflet-popup-tip{background:#1a1a1a!important}
  .leaflet-popup-content{margin:10px 12px!important}
  .pname{font-size:.78rem;font-weight:600;margin-bottom:6px}
  .pvid{width:240px;border-radius:4px;display:block}
</style>
</head>
<body>
<div id="map"></div>

<div id="hud">
  <div id="title">JamCam</div>
  <div id="badge"><div class="pulse"></div><span id="btxt"></span></div>
</div>

<div id="ctrl">
  <div id="rrow">
    <input id="rslider" type="range" min="0.05" max="1" step="0.05" value="0.25">
    <span id="rval">250 m</span>
  </div>
  <button id="clrbtn">clear location</button>
</div>

<button id="geobtn">⦿ Use real location</button>
<div id="tip">Click map to set location — nearby cameras record automatically</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
const CAMS = __CAMS__;

function fmt(km){ return km<1 ? Math.round(km*1000)+' m' : km.toFixed(1)+' km' }
function bust(u){ return u+(u.includes('?')?'&':'?')+'_t='+Date.now() }
function hav(a,b,c,d){
  const R=6371,r=Math.PI/180;
  return R*2*Math.asin(Math.sqrt(Math.sin((c-a)*r/2)**2+Math.cos(a*r)*Math.cos(c*r)*Math.sin((d-b)*r/2)**2));
}

const map = L.map('map',{center:[51.505,-0.1],zoom:13});
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
  attribution:'&copy; OpenStreetMap contributors',maxZoom:19}).addTo(map);

const cluster = L.markerClusterGroup({maxClusterRadius:40,chunkedLoading:true});
map.addLayer(cluster);

const dots={};
CAMS.forEach(c=>{
  const m=L.marker([c.lat,c.lon],{icon:L.divIcon({className:'',html:'<div class="cdot"></div>',iconSize:[8,8],iconAnchor:[4,4]})});
  m.bindPopup(()=>{
    const d=document.createElement('div');
    d.innerHTML=`<div class="pname">${c.name}</div>
      <video class="pvid" src="${bust(c.video)}" autoplay muted loop playsinline></video>`;
    return d;
  },{maxWidth:264});
  cluster.addLayer(m);
  dots[c.id]=m;
});

let lat=null,lon=null,radius=0.25,locM=null,circM=null,geoId=null;
const locIcon=L.divIcon({className:'',html:'<div class="ldot"></div>',iconSize:[16,16],iconAnchor:[8,8]});

async function setLoc(la,lo){
  lat=la; lon=lo;
  if(locM) locM.setLatLng([la,lo]); else locM=L.marker([la,lo],{icon:locIcon,zIndexOffset:2000}).addTo(map);
  redrawCircle(); fade();
  document.getElementById('ctrl').classList.add('on');
  document.getElementById('tip').style.display='none';
  const r=await fetch('/watch',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({lat:la,lon:lo,r:radius})});
  const d=await r.json();
  const b=document.getElementById('badge');
  if(d.n>0){b.classList.add('on');document.getElementById('btxt').textContent=`Recording ${d.n} camera${d.n>1?'s':''}`;}
  else b.classList.remove('on');
}

async function clearLoc(){
  stopGeo(); lat=null; lon=null;
  if(locM){map.removeLayer(locM);locM=null;}
  if(circM){map.removeLayer(circM);circM=null;}
  fade();
  document.getElementById('ctrl').classList.remove('on');
  document.getElementById('tip').style.display='';
  document.getElementById('badge').classList.remove('on');
  await fetch('/unwatch',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
}

function redrawCircle(){
  if(circM)map.removeLayer(circM);
  if(!lat)return;
  circM=L.circle([lat,lon],{radius:radius*1000,color:'#1976d2',weight:1.5,
    fillColor:'#1976d2',fillOpacity:.07,dashArray:'5 4'}).addTo(map);
}

function fade(){
  CAMS.forEach(c=>{
    const m=dots[c.id]; if(!m)return;
    const el=m.getElement(); if(!el)return;
    el.style.opacity=(!lat||hav(lat,lon,c.lat,c.lon)<=radius)?'1':'0.12';
  });
}

map.on('click',e=>{stopGeo();setLoc(e.latlng.lat,e.latlng.lng);});

document.getElementById('rslider').addEventListener('input',async e=>{
  radius=parseFloat(e.target.value);
  document.getElementById('rval').textContent=fmt(radius);
  redrawCircle(); fade();
  if(lat) await setLoc(lat,lon);
});

document.getElementById('clrbtn').addEventListener('click',clearLoc);

function stopGeo(){
  if(geoId!==null){navigator.geolocation.clearWatch(geoId);geoId=null;}
  const b=document.getElementById('geobtn');
  b.classList.remove('on'); b.textContent='⦿ Use real location';
}

document.getElementById('geobtn').addEventListener('click',()=>{
  if(geoId!==null){stopGeo();return;}
  if(!navigator.geolocation){alert('Geolocation not available.');return;}
  const b=document.getElementById('geobtn');
  b.textContent='locating…';
  geoId=navigator.geolocation.watchPosition(
    p=>{b.classList.add('on');b.textContent='⦿ Live location';
        setLoc(p.coords.latitude,p.coords.longitude);
        map.setView([p.coords.latitude,p.coords.longitude],Math.max(map.getZoom(),15));},
    e=>{stopGeo();alert('Location error: '+e.message);},
    {enableHighAccuracy:true,maximumAge:5000});
});
</script>
</body>
</html>
"""


# ── Startup ───────────────────────────────────────────────────────────────────

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception: return "127.0.0.1"


def find_openssl():
    for c in ["openssl", r"C:\Program Files\Git\usr\bin\openssl.exe"]:
        try:
            subprocess.run([c, "version"], capture_output=True, timeout=5, check=True)
            return c
        except Exception: continue
    return None


def make_cert(cert, key):
    openssl = find_openssl()
    if not openssl: raise FileNotFoundError("openssl not found")
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", key, "-out", cert, "-days", "365", "-subj", "/CN=jamcam"],
                   capture_output=True, check=True, timeout=30)


def main():
    use_https = "--https" in sys.argv
    here = os.path.dirname(os.path.abspath(__file__))

    print("Fetching cameras…")
    try:
        Handler.cameras = fetch_cameras()
        print(f"  {len(Handler.cameras)} cameras with video")
    except Exception as e:
        print(f"  Warning: {e}")

    ffmpeg = get_ffmpeg()
    print(f"  ffmpeg: {'bundled via imageio' if ffmpeg else 'not found — run: pip install imageio imageio-ffmpeg'}")

    ip = lan_ip(); scheme = "https" if use_https else "http"
    print(f"\n  Local: {scheme}://localhost:{PORT}")
    print(f"  Phone: {scheme}://{ip}:{PORT}")

    server = ThreadingHTTPServer(("", PORT), Handler)
    if use_https:
        cert = os.path.join(here, "cert.pem"); key = os.path.join(here, "key.pem")
        if not (os.path.exists(cert) and os.path.exists(key)):
            print("\n  Generating certificate…")
            try: make_cert(cert, key)
            except Exception as e:
                print(f"  Failed: {e}\n  Try: ngrok http {PORT}"); sys.exit(1)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        print("  (accept the cert warning on your phone)")

    print(f"\n  Recordings → {REC_DIR}")
    print("  Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFinalising…")
        WATCH.stop()
        time.sleep(4)


if __name__ == "__main__":
    main()
