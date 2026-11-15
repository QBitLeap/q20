"""Collect only checksummed, smoke-tested archives from all five native targets."""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from q20 import __version__
TARGETS=('macos-arm64','macos-x64','windows-x64','linux-x64','linux-arm64')
def collect(source,destination):
 source,destination=Path(source),Path(destination);destination.mkdir(parents=True,exist_ok=True)
 sums=[]
 for target in TARGETS:
  suffix='.zip' if target.startswith('windows') else '.tar.gz';name='q20-'+__version__+'-'+target+suffix;archive=source/target/name;receipt=archive.with_suffix(archive.suffix+'.json');value=json.loads(receipt.read_bytes());digest=hashlib.sha256(archive.read_bytes()).hexdigest()
  if value.get('version')!=__version__ or value.get('sha256')!=digest or any(value.get(k) is not True for k in ('nativePackagingSmokePassed','isolatedProcessPassed','shutdownAccepted','newTipDetected')):raise ValueError('Native archive acceptance differs: '+target)
  shutil.copyfile(archive,destination/name);shutil.copyfile(receipt,destination/receipt.name);sums.append(digest+'  '+name)
 receipt=source/'umbrel/q20-update-receipt.json';value=json.loads(receipt.read_bytes())
 if value.get('version')!=__version__ or value.get('anonymousPullAccepted') is not True or value.get('nativeIntegrationPassed') is not True:raise ValueError('Public Umbrel image acceptance required')
 shutil.copyfile(receipt,destination/receipt.name);(destination/'SHA256SUMS').write_text('\n'.join(sums)+'\n')
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('destination');a=p.parse_args();collect(a.source,a.destination)
