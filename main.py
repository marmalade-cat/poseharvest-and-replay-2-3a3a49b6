#!/usr/bin/env python3
"""
Simple harvester/validator/converter prototype.
- Crawl seeds (polite: single-threaded, obeys robots.txt if reachable).
- Detect linked .csv or .json files and basic inline JSON arrays.
- Validate records have required pose fields.
- Output canonical.ndjson (one JSON object per line) with fields: timestamp, module_id, position:{x,y,z}, orientation:{qx,qy,qz,qw}.

No external deps. Keep modest for demo use only.
"""
import sys, io, os, re, json, time
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen, Request
from html.parser import HTMLParser

USER_AGENT = 'PoseHarvestBot/0.1 (example)'
SEEDS = [
    # Example seed: small local data URI style page (for offline demo) or change to real URLs
    'data:text/html,<html><body><a href="data:text/csv, timestamp,module_id,x,y,z,qx,qy,qz,qw\n0.0,modA,0,0,0,0,0,0,1">example.csv</a></body></html>'
]

# Minimal HTML link parser
class LinkParser(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.links = []
        self.base = base
    def handle_starttag(self, tag, attrs):
        if tag.lower()=='a':
            href = dict(attrs).get('href')
            if href:
                self.links.append(urljoin(self.base, href))

# Basic robots.txt check (very small): fetch and look for Disallow for our UA or '*'
def allowed_by_robots(url):
    parsed = urlparse(url)
    if not parsed.scheme.startswith('http'):
        return True
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        req = Request(robots_url, headers={'User-Agent':USER_AGENT})
        with urlopen(req, timeout=5) as r:
            txt = r.read().decode('utf-8', errors='ignore')
    except Exception:
        return True
    # naive parse
    ua = None
    disallows = []
    for line in txt.splitlines():
        line=line.strip()
        if not line or line.startswith('#'): continue
        if line.lower().startswith('user-agent:'):
            ua = line.split(':',1)[1].strip()
        elif line.lower().startswith('disallow:') and ua in (USER_AGENT, '*'):
            path = line.split(':',1)[1].strip()
            disallows.append(path)
    path = parsed.path or '/'
    for d in disallows:
        if d=='' : return True
        if path.startswith(d):
            return False
    return True

# Fetch a URL (supports data: and http/https)
def fetch(url):
    if url.startswith('data:'):
        # data:<mediatype>,data
        m = url.split(',',1)
        if len(m)<2: return b''
        return m[1].encode('utf-8')
    req = Request(url, headers={'User-Agent':USER_AGENT})
    with urlopen(req, timeout=10) as r:
        return r.read()

# Detect candidate files (CSV or JSON) by URL extension or content start
def is_candidate(url, content):
    if url.lower().endswith('.csv') or url.lower().endswith('.json'):
        return True
    s = content.lstrip()[:50].lower()
    if s.startswith(b'[') or s.startswith(b'{') or b',' in s:
        return True
    return False

# Try parsing CSV into list of dicts
def parse_csv(bs):
    s = bs.decode('utf-8', errors='ignore')
    lines = [l for l in s.splitlines() if l.strip()]
    if not lines: return []
    header = [h.strip() for h in lines[0].split(',')]
    out = []
    for row in lines[1:]:
        vals = [v.strip() for v in row.split(',')]
        if len(vals)<len(header): continue
        d = dict(zip(header, vals))
        out.append(d)
    return out

# Normalize and validate a record; returns canonical dict or None
def validate_record(rec):
    # rec may be dict of strings or already typed
    # Required: timestamp, module_id, position (x,y,z) and orientation (either qx,qy,qz,qw) or euler roll/pitch/yaw
    out = {}
    def get(k):
        return rec.get(k) if isinstance(rec, dict) else None
    ts = get('timestamp') or get('time') or get('t')
    mid = get('module_id') or get('module') or get('id')
    if ts is None or mid is None:
        return None
    try:
        out['timestamp'] = float(ts)
    except Exception:
        return None
    out['module_id'] = str(mid)
    # position
    px = get('x') or get('pos_x') or get('position_x')
    py = get('y') or get('pos_y') or get('position_y')
    pz = get('z') or get('pos_z') or get('position_z')
    if None in (px,py,pz): return None
    try:
        out['position'] = {'x':float(px),'y':float(py),'z':float(pz)}
    except Exception:
        return None
    # orientation: prefer quaternion
    qx = get('qx') or get('orientation_x')
    qy = get('qy') or get('orientation_y')
    qz = get('qz') or get('orientation_z')
    qw = get('qw') or get('orientation_w')
    if None not in (qx,qy,qz,qw):
        try:
            out['orientation'] = {'qx':float(qx),'qy':float(qy),'qz':float(qz),'qw':float(qw)}
            return out
        except Exception:
            return None
    # fallback: euler angles (degrees assumed)
    roll = get('roll') or get('r')
    pitch = get('pitch') or get('p')
    yaw = get('yaw') or get('y')
    if None not in (roll,pitch,yaw):
        try:
            out['orientation'] = {'roll':float(roll),'pitch':float(pitch),'yaw':float(yaw)}
            return out
        except Exception:
            return None
    return None

# Main simple crawl/harvest
def harvest(seeds, outpath='canonical.ndjson', max_pages=20):
    visited = set()
    to_visit = list(seeds)
    canonical = []
    pages = 0
    while to_visit and pages < max_pages:
        url = to_visit.pop(0)
        if url in visited: continue
        visited.add(url)
        pages +=1
        print('FETCH', url)
        if not allowed_by_robots(url):
            print('  blocked by robots:', url)
            continue
        try:
            data = fetch(url)
        except Exception as e:
            print('  fetch failed', e)
            continue
        # if HTML, parse links
        ct = None
        if isinstance(data, bytes):
            sample = data.lstrip()[:50]
            if sample.startswith(b'<'):
                parser = LinkParser(url)
                try:
                    parser.feed(data.decode('utf-8',errors='ignore'))
                    for l in parser.links:
                        if l not in visited and l not in to_visit:
                            to_visit.append(l)
                except Exception:
                    pass
        # candidate file?
        if is_candidate(url, data):
            # try parse JSON
            parsed = None
            try:
                txt = data.decode('utf-8',errors='ignore')
                if txt.lstrip().startswith('['):
                    parsed = json.loads(txt)
                elif txt.lstrip().startswith('{'):
                    j = json.loads(txt)
                    # maybe object with array
                    if isinstance(j, dict):
                        # try to find array field
                        for v in j.values():
                            if isinstance(v, list):
                                parsed = v; break
                else:
                    parsed = None
            except Exception:
                parsed=None
            entries = []
            if parsed and isinstance(parsed, list):
                entries = parsed
            else:
                # try csv
                try:
                    entries = parse_csv(data)
                except Exception:
                    entries = []
            # validate each
            for rec in entries:
                can = validate_record(rec)
                if can:
                    canonical.append(can)
        time.sleep(0.1)
    # write canonical ndjson
    with open(outpath,'w',encoding='utf-8') as f:
        for r in canonical:
            f.write(json.dumps(r)+'\n')
    print('Wrote', outpath, 'records=', len(canonical))

if __name__=='__main__':
    seeds = SEEDS
    if len(sys.argv)>1:
        seeds = sys.argv[1:]
    out = 'canonical.ndjson'
    harvest(seeds, outpath=out)
    print('Done. Open index.html and load', out)
