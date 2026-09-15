import sys, traceback, urllib.request, urllib.error
out = []
try:
    req = urllib.request.Request('http://localhost:20301/api/farm/vehicles')
    req.add_header('Origin', 'http://localhost:20300')
    out.append("requesting...")
    try:
        r = urllib.request.urlopen(req, timeout=5)
        out.append(f"status: {r.status}")
        out.append(f"ACAO: {r.headers.get('access-control-allow-origin')}")
        out.append(f"ACAC: {r.headers.get('access-control-allow-credentials')}")
    except urllib.error.HTTPError as e:
        out.append(f"status: {e.code}")
        out.append(f"ACAO: {e.headers.get('access-control-allow-origin')}")
        out.append(f"ACAC: {e.headers.get('access-control-allow-credentials')}")
        out.append(f"ACAM: {e.headers.get('access-control-allow-methods')}")
        out.append(f"body: {e.read()[:200].decode('utf-8', errors='replace')}")
    except Exception as e:
        out.append(f"EXC: {type(e).__name__}: {e}")
except Exception as e:
    out.append(f"outer EXC: {type(e).__name__}: {e}")
    out.append(traceback.format_exc())

with open('_check_out.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('done')
