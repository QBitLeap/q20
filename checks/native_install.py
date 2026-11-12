"""Disposable native process acceptance; no operator data or public peers."""
from http.server import BaseHTTPRequestHandler
import base64
import json
import os
from pathlib import Path
import subprocess
import socket
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import build_opener,ProxyHandler,Request
ROOT=Path('/opt/q20') if Path('/opt/q20/q20').is_dir() else Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from q20.http import Server
from q20.rules import Rules


def check():
    rules=Rules.load();genesis=rules.value['genesis'];tip=[0];calls=[];opener=build_opener(ProxyHandler({}))
    token='1'*64
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    class Core(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            r=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=r['method'];calls.append(method)
            if method=='getblockchaininfo':value={'chain':'main','blocks':tip[0],'headers':tip[0],'initialblockdownload':False}
            elif method=='getblockhash' and r['params']==[0]:value=genesis
            elif method=='getblock' and r['params']==[genesis,3]:value={'height':0,'hash':genesis,'tx':[{'txid':'a'*64,'version':2,'locktime':0,'vin':[{'coinbase':'00'}],'vout':[{'value_bits':0,'scriptPubKey':{'hex':'6a'}}]}]}
            elif method=='gettxout':value={'confirmations':1}
            else:raise AssertionError('Unapproved fixture method '+method)
            body=json.dumps({'result':value,'error':None,'id':r['id']}).encode();self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=Server(('127.0.0.1',0),Core);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    auth='Basic '+base64.b64encode(('reader:'+token).encode()).decode()
    def read(port,path,body=None,credential=auth):
        request=Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(body).encode() if body else None,headers={'Authorization':credential,'Content-Type':'application/json'})
        with opener.open(request,timeout=3) as response:return json.load(response)
    with tempfile.TemporaryDirectory(prefix='q20-native-fixture-') as directory:
        before=None
        try:
            for restart in range(2):
                process=subprocess.Popen([sys.executable,'-B','-m','q20','start','--data',directory,'--rpc-url',f'http://127.0.0.1:{server.server_port}','--port',str(port)],env={**os.environ,'Q20_CORE_READ_TOKEN':'2'*64,'Q20_API_TOKEN':token},cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                try:
                    for _ in range(150):
                        if process.poll() is not None:raise AssertionError(process.communicate()[1].decode())
                        try:
                            if read(port,'/v1/status').get('observedSynchronized'):break
                        except OSError:pass
                        time.sleep(.1)
                    else:raise AssertionError('Native index did not reach fixture tip')
                    status=read(port,'/v1/status');assert status['rulesFingerprint']==rules.fingerprint and status['indexHash']==genesis
                    try:read(port,'/v1/tokens',credential='Basic invalid')
                    except HTTPError as error:assert error.code==401
                    else:raise AssertionError('Missing API authentication')
                    assert read(port,'/v1/protection',{'coins':[{'txid':'b'*64,'vout':0}]})['coins'][0]['protected'] is False
                    tip[0]=1
                    try:read(port,'/v1/protection',{'coins':[{'txid':'b'*64,'vout':0}]})
                    except HTTPError as error:assert error.code==503
                    else:raise AssertionError('Stale index must refuse protection')
                    tip[0]=0
                    if before is not None:assert status['indexHeight']==before['indexHeight']
                    before=status
                finally:
                    process.terminate()
                    try:stdout,stderr=process.communicate(timeout=15)
                    except subprocess.TimeoutExpired:process.kill();process.communicate();raise AssertionError('Unclean q20 stop')
                    assert process.returncode==0,stderr.decode()
            assert calls.count('getblock')==1,'Restart or idle re-fetched existing block'
        finally:server.shutdown();server.server_close();thread.join(5)
    return {'passed':True,'nativeProcess':True,'apiAuthentication':True,'freshProtection':True,'staleIndexRefused':True,'restartPersistence':True,'cleanStop':True,'noRedundantBlockReads':True,'productionServicesStarted':False,'operationalDataMounted':False,'peerNetworkingEnabled':False,'realChainParityAccepted':False}


if __name__=='__main__':print(json.dumps(check(),indent=2))
