"""Publish the exact accepted native image; never rebuild or mutate its layers."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
VERSION='0.1.1'
NATIVE_SOURCE='e675c2ae85d9100f705e6f448bac42180dc95ae0'
NATIVE_RUN=43145709674
ARCHIVE_SHA='dbcd40a2aa2be87c03c30c92e9a8c527641cb856c198f9eb7bea979063b9156f'
IMAGE='sha256:0c1d5ce05023985360e4d92cd9fb12e2e0f36b59b327f4ad81be02c22bca9c1e'
TAG='ghcr.io/qbitleap/q20:'+VERSION


def run(argv):return subprocess.check_output(argv,cwd=ROOT,text=True,stderr=subprocess.STDOUT,timeout=300).strip()


def verify_archive(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('Verified native image archive required')
    if sha256(path.read_bytes()).hexdigest()!=ARCHIVE_SHA:raise ValueError('Native archive differs from accepted artifact')


def release(path,output,publish=False):
    verify_archive(path)
    # Docs, packaging and checks can change without changing an accepted engine.
    run(['git','diff','--exit-code',NATIVE_SOURCE,'HEAD','--','q20','Dockerfile','scripts/build_crypto.py','third_party'])
    if subprocess.run(['docker','image','inspect',IMAGE],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:run(['docker','load','--input',str(path)])
    info=json.loads(run(['docker','image','inspect',IMAGE]))[0]
    if info['Id']!=IMAGE or info['Architecture']!='amd64' or info['Os']!='linux':raise ValueError('Native image identity/platform differs')
    version=run(['docker','run','--rm','--network','none','--read-only','--user','1000:1000','--cap-drop','ALL','--security-opt','no-new-privileges:true','--tmpfs','/tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777',IMAGE,'--version'])
    if version!=VERSION:raise ValueError('Native CLI version differs')
    receipt={'version':VERSION,'imageId':IMAGE,'nativeArchiveSha256':ARCHIVE_SHA,'nativeSourceCommit':NATIVE_SOURCE,'nativeWorkflowRun':NATIVE_RUN,'packagingCommit':run(['git','rev-parse','HEAD']),'engineRecompiled':False,'published':False,'anonymousPullAccepted':False,'managedInstallationAccepted':False,'liveChainParityAccepted':False}
    if publish:
        integration=json.loads((output.parent/'integration.json').read_text())
        if integration.get('passed') is not True or integration.get('imageId')!=IMAGE or integration.get('networks',{}).get('main',{}).get('fixtureCleanupComplete') is not True:raise ValueError('Passing integration and cleanup for this exact image required')
        run(['docker','tag',IMAGE,TAG]);run(['docker','push',TAG])
        info=json.loads(run(['docker','image','inspect',TAG]))[0]
        refs=[r for r in info.get('RepoDigests',[]) if re.fullmatch(r'ghcr.io/qbitleap/q20@sha256:[0-9a-f]{64}',r)]
        if info['Id']!=IMAGE or len(refs)!=1:raise ValueError('Published image identity differs')
        receipt.update(published=True,image=refs[0],tag=TAG,integrationPassed=True)
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(receipt,indent=2)+'\n');return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--publish',action='store_true');args=parser.parse_args()
    print(json.dumps(release(args.archive,args.output,args.publish),indent=2))
