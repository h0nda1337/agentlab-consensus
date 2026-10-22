"""Small OpenAI-compatible JSON transport shared by the coding team."""
import json
import urllib.error
import urllib.request


def request(url, payload=None, timeout=300):
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Servidor local rechazó la solicitud (HTTP {exc.code}).') from None
    except Exception:
        raise RuntimeError('Servidor local no disponible o respuesta inválida.') from None
