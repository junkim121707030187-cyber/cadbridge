from pathlib import Path
import urllib.request
import json
root=Path(__file__).resolve().parent.parent
info=json.loads((root/'data/server.json').read_text(encoding='utf-8'))
url=info['url']
if not url.startswith('http://127.0.0.1:'):
    raise ValueError('Invalid local server URL')
with urllib.request.urlopen(url+'/api/bootstrap',timeout=30) as response:
    bootstrap=json.load(response)
if bootstrap.get('application')!='cadbridge-local-prototype':
    raise ValueError('Different application')
request=urllib.request.Request(url+'/api/stop',data=b'{}',headers={'X-CADBridge-Token':bootstrap['token'],'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=5) as response:
    response.read()
