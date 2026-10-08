"""Self-contained read-only HTML exports using the same dashboard UI."""
import copy
import json
import os
import re
import sys
from pathlib import Path


def ui_directory():
    if getattr(sys,"frozen",False):
        base=Path(getattr(sys,"_MEIPASS",os.environ.get("RESOURCEPATH",Path(sys.executable).parent.parent/"Resources")))
        return base/'ui' if (base/'ui').exists() else base/'dist'
    packaged = Path(__file__).parent / "ui"
    return packaged if packaged.exists() else Path(__file__).resolve().parents[2] / "frontend" / "dist"


def anonymize(value):
    data = copy.deepcopy(value)
    projects = {p["id"]:{"id":f"project-{i+1}","name":f"Project {i+1}"} for i,p in enumerate(data["options"]["projects"])}
    for p in data["projects"]:
        replacement = projects[p["project_id"]]
        p.update(project_id=replacement["id"],name=replacement["name"])
    data["options"]["projects"] = list(projects.values())
    if data.get('filters',{}).get('project_id'):
        data['filters']['project_id']=projects[data['filters']['project_id']]['id']
    for i,source in enumerate(data["sources"]):
        if data.get('filters',{}).get('source_id')==source['id']:
            data['filters']['source_id']=f"source-{i+1}"
        source.update(id=f"source-{i+1}",label=f"Source {i+1}",root=None,detail="")
    data["settings"]["device_label"] = "This computer"
    return data


def export_html(value, destination, anonymous=True):
    data = anonymize(value) if anonymous else copy.deepcopy(value)
    for source in data["sources"]:
        source["root"] = None
    data.update(readonly=True,exporter=False,job={"running":False,"message":"Saved snapshot","error":None,"progress":{}})
    directory = ui_directory()
    if not (directory/"index.html").exists():
        raise ValueError("Build the UI first: cd frontend && npm run build")
    html = (directory/"index.html").read_text(encoding="utf-8")
    def js(match):
        path = directory / match[1].lstrip("/")
        return '<script type="module">'+path.read_text(encoding="utf-8").replace('</script','<\\/script')+'</script>'
    def css(match):
        path = directory / match[1].lstrip("/")
        return '<style>'+path.read_text(encoding="utf-8")+'</style>'
    html = re.sub(r'<script[^>]*src="([^"]+)"[^>]*></script>',js,html)
    html = re.sub(r'<link[^>]*href="([^"]+\.css)"[^>]*>',css,html)
    safe = json.dumps(data).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    html = html.replace('<head>','<head><script>window.__INSIGHTS_REPORT__='+safe+';</script>',1)
    html = html.replace('__INSIGHTS_TOKEN__','')
    Path(destination).write_text(html,encoding="utf-8")
    return {"path":str(destination),"bytes":Path(destination).stat().st_size}
