"""Owned Docker fixtures shared with the QBitLeap community catalog tests.

Adapted from QBitLeap/umbrel-app-store checks/integration.py at
132e2757a84cb277a006849a76e88bcf806af292 (MIT). No operational mounts.
"""
import json
import secrets
import subprocess
import time
import uuid
GENESIS={"main":"0000000000004d60aa5d46013991d0a0e2995d89ee98e53068ae196d763e79f2"}
PURPOSE="q20-community-fixture"


class Docker:
 def __init__(self): self.prefix=["docker", "--host", "unix:///var/run/docker.sock"]
 def call(self,args,timeout=30,check=True):
  value=subprocess.run(self.prefix+args,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
  if check and value.returncode: raise RuntimeError("Docker operation failed: "+value.stderr.strip()[:2000])
  return value
 def inspect(self,kind,name): return json.loads(self.call([kind,"inspect",name]).stdout)[0]
 def ensure_image(self,image):
  if self.call(["image","inspect",image],check=False).returncode:
   self.call(["pull",image],timeout=300)

def fixture_mounts_only(mounts, volumes):
    return all((m.get("Type") == "volume" and m.get("Name") in volumes
                and m.get("Destination") in {"/data", "/auth", "/settings"})
               or (m.get("Type") == "tmpfs" and m.get("Destination") == "/tmp")
               for m in mounts)

class Fixture:

    def __init__(self, docker, images, chain):
        (self.docker, self.images, self.chain) = (docker, images, chain)
        self.run_id = uuid.uuid4().hex
        self.prefix = 'qbitleap-fixture-' + self.run_id[:12]
        (self.containers, self.volumes) = ([], [])
        self.network = None
        self.ingress = None

    def labels(self):
        return ['--label', 'qbitleap.run=' + self.run_id, '--label', 'qbitleap.purpose=' + PURPOSE]

    def volume(self, name):
        name = self.prefix + '-' + name
        if self.docker.call(['volume', 'inspect', name], check=False).returncode == 0:
            raise RuntimeError('Fixture volume exists; preserve it')
        self.docker.call(['volume', 'create', *self.labels(), name])
        self.volumes.append(name)
        return name

    def start(self, suffix, image, command, environment, *, share=None, volumes=(), memory='512m'):
        self.docker.ensure_image(image)
        name = self.prefix + '-' + suffix
        if self.docker.call(['container', 'inspect', name], check=False).returncode == 0:
            raise RuntimeError('Fixture container exists; preserve it')
        args = ['run', '--detach', '--init', '--pull=never', '--name', name, *self.labels(), '--network', 'container:' + share if share else self.network, '--read-only', '--user', '1000:1000', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges=true', '--pids-limit', '256', '--cpus', '2', '--memory', memory, '--memory-swap', memory, '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=64m,mode=1777']
        for (key, value) in environment.items():
            args += ['--env', key + '=' + value]
        for (volume, target, readonly) in volumes:
            if volume not in self.volumes or target not in {'/data', '/auth', '/settings'}:
                raise RuntimeError('Unexpected fixture mount')
            args += ['--mount', 'type=volume,src=' + volume + ',dst=' + target + (',readonly' if readonly else '')]
        self.containers.append(name)
        self.docker.call(args + [image, *command])
        info = self.docker.inspect('container', name)
        host = info['HostConfig']
        if info['Config'].get('User') != '1000:1000' or host.get('Binds') or host.get('Privileged') or host.get('PortBindings') or (not host.get('ReadonlyRootfs')) or (host.get('Init') is not True) or ('ALL' not in host.get('CapDrop', [])) or (not fixture_mounts_only(info.get('Mounts', []), self.volumes)):
            raise RuntimeError('Fixture isolation differs')
        return name

    def probe(self, container, url, *, body=None, role=None, token_env=None, headers=None):
        code = "import os,json,base64\nfrom urllib.request import Request,urlopen\nfrom urllib.error import HTTPError\nurl=URL\nheaders={'Content-Type':'application/json', **EXTRA_HEADERS}\nif ROLE is not None:\n headers['Authorization']='Basic '+base64.b64encode((ROLE+':'+os.environ[TOKEN_ENV]).encode()).decode()\ndata=DATA\nrequest=Request(url,data=None if data is None else json.dumps(data).encode(),headers=headers)\ntry:\n with urlopen(request,timeout=4) as response: code,raw=response.status,response.read(1048576)\nexcept HTTPError as response: code,raw=response.code,response.read(1048576)\ntry:value=json.loads(raw)\nexcept Exception:value=None\nprint(json.dumps({'status':code,'body':value}))\n".replace('URL', repr(url)).replace('ROLE', repr(role)).replace('TOKEN_ENV', repr(token_env)).replace('DATA', repr(body)).replace('EXTRA_HEADERS', repr(headers or {}))
        value = self.docker.call(['exec', '--user', '1000:1000', container, 'python3', '-c', code], timeout=10)
        return json.loads(value.stdout)

    def wait(self, function, names, timeout=75):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            for name in names:
                if not self.docker.inspect('container', name)['State']['Running']:
                    log = self.docker.call(['logs', '--tail', '15', name], check=False)
                    raise RuntimeError('Fixture exited: ' + (log.stdout + log.stderr)[-2500:])
            try:
                last = function()
                if last.get('status') == 200:
                    return last
            except Exception as error:
                last = str(error)
            time.sleep(1)
        raise RuntimeError('Fixture readiness timed out: ' + str(last)[:1000])

    def cleanup(self):
        errors = []
        groups = [('container', list(reversed(self.containers))), ('volume', list(reversed(self.volumes))), ('network', [name for name in (self.ingress, self.network) if name])]
        for (kind, names) in groups:
            for name in names:
                try:
                    info = self.docker.inspect(kind, name)
                    labels = info.get('Labels', {}) if kind != 'container' else info['Config'].get('Labels', {})
                    if labels.get('qbitleap.run') != self.run_id or labels.get('qbitleap.purpose') != PURPOSE:
                        raise RuntimeError('Ownership differs; cleanup refused')
                    if kind == 'container':
                        self.docker.call(['stop', '--time', '30', name], timeout=40, check=False)
                        self.docker.call(['rm', '--force', name])
                    else:
                        self.docker.call([kind, 'rm', name])
                except Exception as error:
                    errors.append({'kind': kind, 'name': name, 'error': str(error)})
        return errors

    def diagnostics(self):
        report = {}
        for name in self.containers:
            try:
                info = self.docker.inspect('container', name)
                labels = info['Config'].get('Labels', {})
                if labels.get('qbitleap.run') != self.run_id:
                    continue
                log = self.docker.call(['logs', '--tail', '20', name], check=False)
                namespace = self.docker.call(['exec', name, 'readlink', '/proc/self/ns/net'], check=False)
                report[name.removeprefix(self.prefix + '-')] = {'running': info['State'].get('Running'), 'exitCode': info['State'].get('ExitCode'), 'networkNamespace': namespace.stdout.strip(), 'logTail': (log.stdout + log.stderr)[-4000:]}
            except Exception as error:
                report[name] = {'diagnosticError': str(error)[:300]}
        for (suffix, role, token_env, host) in [('broker', 'reader', 'QBIT_READ_TOKEN', '127.0.0.1'), ('core-ui', 'ui', 'QBIT_UI_TOKEN', self.prefix + '-core')]:
            name = self.prefix + '-' + suffix
            if name not in self.containers:
                continue
            reads = {}
            for (method, params) in [('getblockchaininfo', []), ('getindexinfo', ['txindex']), ('getnetworkinfo', [])]:
                try:
                    reads[method] = self.probe(name, 'http://' + host + ':8081/', body={'id': 1, 'method': method, 'params': params}, role=role, token_env=token_env)
                except Exception as error:
                    reads[method] = {'diagnosticError': str(error)[:500]}
            report.setdefault(suffix, {})['readProbes'] = reads
        return report
