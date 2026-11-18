import json, os, urllib.request, urllib.error
from .. import database as db
KEY=os.environ.get('LLM_API_KEY','')
class ProviderError(Exception): pass
def settings(): return json.loads(db.one('SELECT value FROM settings WHERE id=1')['value'])
def api_json(url,payload,key):
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
    try:
        with urllib.request.urlopen(req,timeout=45) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401,403): raise ProviderError('The provider rejected your API key. Check it in Settings.')
        if e.code==429: raise ProviderError('Provider rate limit or quota reached. Try again later.')
        raise ProviderError(f'Provider returned HTTP {e.code}. Check the model and endpoint in Settings.')
    except Exception as e: raise ProviderError('Could not reach the provider. Check the endpoint, network, or timeout.') from e
class LLMProvider:
    def respond(self,messages): raise NotImplementedError
class OpenAICompatibleProvider(LLMProvider):
    def __init__(self,s): self.s=s
    def respond(self,messages):
        if not KEY: raise ProviderError('Connect an API key in Settings to receive AI responses. Memory processing remains available.')
        data=api_json(self.s['base_url'].rstrip('/')+'/chat/completions',{'model':self.s['model'],'messages':messages,'temperature':0.3},KEY)
        try: content=data['choices'][0]['message']['content']
        except (KeyError,IndexError,TypeError): raise ProviderError('The provider returned a malformed response.')
        if not isinstance(content,str) or not content.strip(): raise ProviderError('The provider returned an empty response.')
        return content.strip()
def get_provider(): return OpenAICompatibleProvider(settings())
def set_key(value):
    global KEY
    KEY=value
