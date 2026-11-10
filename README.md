PoseHarvest-and-Replay-2

A tiny prototype: a Python single-file harvester/validator/converter (main.py) plus an index.html replay UI. Run main.py to crawl seed URLs (defaults include a small local example), detect CSV/JSON files, validate records for fields: timestamp, module_id, position.x/y/z, and orientation (qx,qy,qz,qw or euler roll/pitch/yaw). It writes canonical NDJSON (records one-per-line). Open index.html in a browser and load the produced canonical.ndjson to animate simple 3D boxes using WebGL via a tiny inline renderer.

No dependencies. This is an untested but complete prototype; adjust seeds and user-agent before wide crawling. Interpretation: validation rules are conservative: missing required fields will skip files. See main.py comments for details.