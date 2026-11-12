"""Isolated native q20/Core integration for the community package. No live chain."""
import argparse
import json
from pathlib import Path
import re
import secrets
import signal
import sys
from fixture_helpers import Docker,Fixture,GENESIS

CORE='ghcr.io/qbitleap/qbit-core@sha256:af9aca0fe1805090eb6b503505b659af434798d852a6b8efe6341bf1d5d65761'
SERVICES='ghcr.io/qbitleap/qbit-core-services@sha256:8f6f91e8fbcdc59b67fb7cffd5bc7c105e2b9ea40957444838a6f7a32cac90b8'
ACCEPTED_IMAGE='sha256:0c1d5ce05023985360e4d92cd9fb12e2e0f36b59b327f4ad81be02c22bca9c1e'
Q20=ACCEPTED_IMAGE
RULES='273ee09c9c5eae7c490fd594c58417baf9b78f9b35e15a1a2f1ca1fdd6d9cde6'
CLI_VERSION='0.1.1'

def checked_cli_version(value,status):
    version=value.stdout.strip()
    if value.returncode!=0 or version!=CLI_VERSION or status.get('version')!=CLI_VERSION:
        raise RuntimeError('Native q20 CLI version differs: expected '+CLI_VERSION+', received '+repr(version[:160])+'; API '+repr(status.get('version')))
    return version


class Q20Fixture(Fixture):
    def run(self):
        result={'passed':False,'chain':'main','runId':self.run_id,'protocols':{},'operationalDataMounted':False,'peerNetworkingEnabled':False,'productionServicesStarted':False,'appsInstalled':False,'catalogStarted':False,'websiteConnected':False}
        try:
            self.network=self.prefix+'-private';self.docker.call(['network','create','--internal',*self.labels(),self.network])
            if self.docker.inspect('network',self.network).get('Internal') is not True:raise RuntimeError('Fixture network permits external traffic')
            data,auth,settings=self.volume('core-data'),self.volume('core-auth'),self.volume('core-settings');read,ui_token=secrets.token_hex(32),secrets.token_hex(32)
            result['stage']='isolated real Core and authenticated read gateway'
            core=self.start('core',CORE,['serve'],{'QBIT_CHAIN':'main','QBIT_NETWORK_ACTIVE':'0','QBIT_WALLET_ENABLED':'0'},volumes=[(data,'/data',False),(auth,'/auth',False),(settings,'/settings',False)],memory='1536m')
            broker=self.start('broker',SERVICES,['broker'],{'QBIT_CHAIN':'main','QBIT_READ_TOKEN':read,'QBIT_UI_TOKEN':ui_token},share=core,volumes=[(auth,'/auth',True)],memory='1024m')
            ui=self.start('core-ui',SERVICES,['ui'],{'QBIT_CHAIN':'main','QBIT_READ_URL':'http://'+core+':8081/','QBIT_UI_TOKEN':ui_token})
            query={'jsonrpc':'2.0','id':1,'method':'getblockchaininfo','params':[]}
            def core_ready():
                value=self.probe(broker,'http://127.0.0.1:8081/',body=query,role='reader',token_env='QBIT_READ_TOKEN')
                if value.get('body',{}).get('error'):return {**value,'status':503}
                return value
            node=self.wait(core_ready,[core,broker])['body']['result']
            if node.get('chain')!='main' or node.get('blocks')!=0:raise RuntimeError('Expected correct-network empty fixture Core')
            core_status=self.wait(lambda:self.probe(ui,'http://127.0.0.1:8080/api/status'),[core,broker,ui])['body']
            if core_status.get('bestBlockHash')!=GENESIS['main'] or core_status.get('peerNetworkingEnabled') is not False or core_status.get('connections')!=0:raise RuntimeError('Core fixture identity or peer isolation differs')
            print('Core browser status and isolated Mainnet genesis passed',flush=True)
            if self.probe(ui,'http://'+core+':8081/',body=query)['status']!=401:raise RuntimeError('Core read authentication failed')
            denied=self.probe(broker,'http://127.0.0.1:8081/',body={**query,'method':'sendrawtransaction'},role='reader',token_env='QBIT_READ_TOKEN')
            if denied['status']!=400:raise RuntimeError('Core read gateway accepted publication')
            error=self.probe(broker,'http://127.0.0.1:8081/',body={**query,'method':'getblockhash','params':[1]},role='reader',token_env='QBIT_READ_TOKEN')
            if error.get('body',{}).get('error',{}).get('code')!=-8:raise RuntimeError('Normal Core chain-tip error was not preserved')
            result['core']={**core_status,'readAuthenticationAccepted':True,'publicationRpcRejected':True,'tipErrorCodePreserved':True}
            print('Checking isolated q20 image, data, API and restart',flush=True)
            result['stage']='q20 initialization and Core identity'
            qdata=self.volume('q20-data');api=secrets.token_hex(32)
            qenv={'Q20_CORE_READ_URL':'http://'+core+':8081/','Q20_CORE_READ_TOKEN':read,'Q20_API_TOKEN':api,'Q20_ALLOWED_HOSTS':'*'}
            writer=self.start('q20',Q20,['start','--data','/data','--listen','0.0.0.0','--port','8080'],qenv,volumes=[(qdata,'/data',False)],memory='1024m')
            def q20_ready():
                value=self.probe(writer,'http://127.0.0.1:8080/v1/status',role='reader',token_env='Q20_API_TOKEN')
                body=value.get('body',{})
                if body.get('indexHeight')!=0 or body.get('indexHash')!=GENESIS['main']:return {**value,'status':503}
                return value
            status=self.wait(q20_ready,[core,broker,writer],timeout=100)['body']
            result['q20BeforeRestart']=status
            if status.get('network')!='mainnet' or status.get('rulesFingerprint')!=RULES or status.get('available') is not True or status.get('observedSynchronized') is not False:raise RuntimeError('q20 fixture network, rules or readiness differs')
            result['stage']='q20 native CLI version and API authentication'
            version=checked_cli_version(self.docker.call(['exec',writer,'python','-m','q20','--version']),status)
            if self.probe(writer,'http://127.0.0.1:8080/v1/status')['status']!=401:raise RuntimeError('q20 API accepted unauthenticated reads')
            if self.probe(writer,'http://127.0.0.1:8080/')['status']!=200:raise RuntimeError('q20 dashboard unavailable')
            if self.probe(writer,'http://127.0.0.1:8080/v1/sendrawtransaction',body={},role='reader',token_env='Q20_API_TOKEN')['status']!=404:raise RuntimeError('q20 exposed a publication route')
            pending=self.probe(writer,'http://127.0.0.1:8080/v1/protection',body={'coins':[{'txid':'b'*64,'vout':0}]},role='reader',token_env='Q20_API_TOKEN')
            if pending['status']!=503 or pending.get('body',{}).get('available') is not False:raise RuntimeError('Empty unsynchronized chain must not authorize spending')
            # Only the owned fixture receives a marker; never operational index paths.
            self.docker.call(['exec',writer,'python','-c',"from pathlib import Path;Path('/data/.fixture-restart').write_text('owned-q20-fixture')"])
            self.docker.call(['exec',writer,'python','-c',"from pathlib import Path;assert not Path('/auth/.cookie').exists()"])
            self.docker.call(['exec',writer,'python','-c',"import socket;s=socket.socket();s.settimeout(2);r=s.connect_ex(("+repr(core)+",18443));s.close();assert r!=0"])
            duplicate_code="""from q20.runtime import writer_lock
try:
 with writer_lock('/data'):pass
except ValueError as error:
 if str(error)!='Another q20 process already owns this index':raise
 print('duplicate-writer-refused')
else:raise AssertionError('Duplicate writer accepted')
"""
            duplicate=self.docker.call(['exec',writer,'python','-c',duplicate_code],check=False)
            if duplicate.returncode!=0 or duplicate.stdout.strip()!='duplicate-writer-refused':raise RuntimeError('q20 duplicate writer lock was not established')
            wrong="""import os
from q20.rpc import Core
from q20.rules import Rules
from q20.messages import Incomplete
r=Rules.load();r.value['genesis']='00'*32
try:Core(os.environ['Q20_CORE_READ_URL'],gateway_token=os.environ['Q20_CORE_READ_TOKEN']).identity(r)
except Incomplete as error:
 assert 'network/genesis' in str(error)
else:raise AssertionError('Wrong genesis accepted')
"""
            self.docker.call(['exec',writer,'python','-c',wrong])
            result['stage']='q20 clean stop and persistent-data restart'
            self.docker.call(['stop','--time','30',writer],timeout=40)
            stopped=self.docker.inspect('container',writer)['State']
            if stopped.get('OOMKilled') or stopped.get('ExitCode')!=0:raise RuntimeError('q20 did not stop cleanly')
            self.docker.call(['start',writer]);again=self.wait(q20_ready,[core,broker,writer])['body']
            self.docker.call(['exec',writer,'python','-c',"from pathlib import Path;assert Path('/data/.fixture-restart').read_text()=='owned-q20-fixture'"])
            if any(again.get(k)!=status.get(k) for k in ('network','rulesFingerprint','indexHeight','indexHash')):raise RuntimeError('q20 state changed across restart')
            result['stage']='coupled Core/gateway restart and q20 recovery'
            self.docker.call(['stop','--time','30',broker],timeout=40);self.docker.call(['stop','--time','30',core],timeout=40)
            if self.docker.inspect('container',core)['State'].get('ExitCode')!=0:raise RuntimeError('Fixture Core did not stop cleanly')
            self.docker.call(['start',core]);self.docker.call(['start',broker]);self.wait(core_ready,[core,broker]);self.wait(q20_ready,[core,broker,writer])
            self.docker.call(['exec',writer,'python','-c',"import os;from q20.rpc import Core;from q20.rules import Rules;assert Core(os.environ['Q20_CORE_READ_URL'],gateway_token=os.environ['Q20_CORE_READ_TOKEN']).identity(Rules.load())['chain']=='main'"])
            result['protocols']['q20']={**status,'apiAuthenticationAccepted':True,'readGatewayIntegrationAccepted':True,'restartAccepted':True,'fixtureDataSurvivedRestart':True,'duplicateWriterRefused':True,'wrongGenesisRejected':True,'coreCookieAbsent':True,'rawRpcNotReachable':True,'publicationRouteAbsent':True,'unsynchronizedProtectionRefused':True,'coreAndGatewayRestartAccepted':True,'cleanStopExitCode':stopped['ExitCode'],'nativeCliVersion':version}
            result.update(passed=True,stage='all isolated q20 app checks passed')
        except BaseException as error:
            result['error']=str(error);result['diagnostics']=self.diagnostics()
        finally:
            errors=self.cleanup();result['fixtureCleanupComplete']=not errors;result['cleanupErrors']=errors
            if errors:result['passed']=False
        return result


def main():
    global Q20
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',default=ACCEPTED_IMAGE)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.image!=ACCEPTED_IMAGE and not re.fullmatch(r'ghcr.io/qbitleap/q20@sha256:[0-9a-f]{64}',args.image):raise SystemExit('Pinned accepted q20 image required')
    if args.output.exists() or args.output.is_symlink():raise SystemExit('New evidence output required')
    Q20=args.image;docker=Docker()
    for image in (CORE,SERVICES,Q20):docker.ensure_image(image)
    info=docker.inspect('image',Q20)
    if info.get('Id')!=ACCEPTED_IMAGE or info.get('Architecture')!='amd64' or info.get('Os')!='linux':raise SystemExit('Image differs from owner-accepted native image')
    result=Q20Fixture(docker,{'core':CORE,'services':SERVICES,'q20':Q20},'main').run()
    receipt={'passed':result['passed'],'network':'main','images':{'core':CORE,'services':SERVICES,'q20':Q20},'imageId':ACCEPTED_IMAGE,'networks':{'main':result},'productionServicesStarted':False,'operationalDataMounted':False,'peerNetworkingEnabled':False,'appsInstalled':False,'publicLiveRoutingAccepted':False,'realChainParityAccepted':False}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2));return 0 if receipt['passed'] else 1


if __name__=='__main__':
    def interrupted(*_):raise KeyboardInterrupt('Fixture validation interrupted')
    signal.signal(signal.SIGTERM,interrupted);sys.exit(main())
