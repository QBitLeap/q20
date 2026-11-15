"""Publish only the exact newly built image after its isolated integration passes."""
import argparse,hashlib,json,os,re,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def run(args,env=None):return subprocess.check_output(args,cwd=ROOT,env=env,text=True,timeout=900).strip()
def publish(image,integration,output):
 if re.fullmatch(r'sha256:[0-9a-f]{64}',image) is None:raise ValueError('Exact built image ID required')
 value=json.loads(Path(integration).read_bytes());proof=value.get('networks',{}).get('main',{})
 if value.get('passed') is not True or value.get('imageId')!=image or proof.get('fixtureCleanupComplete') is not True or value.get('operationalDataMounted') is not False or value.get('productionServicesStarted') is not False:raise ValueError('Passing exact-image integration and cleanup required')
 from sys import path
 path.insert(0,str(ROOT));from q20 import __version__
 tag='ghcr.io/qbitleap/q20:'+__version__;run(['docker','tag',image,tag]);run(['docker','push',tag]);metadata=json.loads(run(['docker','image','inspect',tag]))[0]
 refs=[v for v in metadata.get('RepoDigests',[]) if re.fullmatch(r'ghcr.io/qbitleap/q20@sha256:[0-9a-f]{64}',v)]
 if metadata['Id']!=image or len(refs)!=1:raise ValueError('Published configuration identity differs')
 with tempfile.TemporaryDirectory(prefix='q20-anonymous-') as directory:
  environment={**os.environ,'DOCKER_CONFIG':directory};run(['docker','pull',refs[0]],environment)
 if json.loads(run(['docker','image','inspect',refs[0]]))[0]['Id']!=image:raise ValueError('Anonymous digest pull differs')
 result=dict(version=__version__,sourceCommit=run(['git','rev-parse','HEAD']),imageId=image,imageReference=refs[0],anonymousPullAccepted=True,nativeIntegrationPassed=True,fixtureCleanupComplete=True,managedInstallationAccepted=False,liveChainParityAccepted=False,indexSchemaChanged=False,rulesChanged=False,tipPollSeconds=20,unchangedTipLedgerWrites=False)
 Path(output).write_text(json.dumps(result,indent=2)+'\n');return result
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',required=True);p.add_argument('--integration',required=True);p.add_argument('--output',required=True);a=p.parse_args();print(json.dumps(publish(a.image,a.integration,a.output),indent=2))
