#!/usr/bin/env python3
"""Inspect and bump pinned Sugarkube app Helm chart versions."""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, urllib.request
from pathlib import Path
import app_config

SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
REQ_ENV = {"tokenplace":["TOKENPLACE_IMAGE_TAG","TOKENPLACE_RELEASE_VERSION","TOKENPLACE_CHART_VERSION","TOKENPLACE_DEPLOY_ENV"]}
ROOT=Path(__file__).resolve().parents[1]

def read_pin(path: str) -> str:
    p=(ROOT/path) if not Path(path).is_absolute() else Path(path)
    for line in p.read_text().splitlines():
        v=line.split('#',1)[0].strip()
        if v: return v
    raise SystemExit(f"ERROR: chart pin file {path} did not contain a version")

def run(args:list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args,capture_output=True,text=True,check=False)

def chart_meta(ref:str, ver:str) -> tuple[dict[str,str], str]:
    cp=run(["helm","show","chart",ref,"--version",ver])
    if cp.returncode: raise SystemExit(cp.stderr or cp.stdout)
    meta={}
    for line in cp.stdout.splitlines():
        if ':' in line and not line.startswith(' '):
            k,v=line.split(':',1); meta[k.strip()]=v.strip().strip('"')
    digest=meta.get('digest') or meta.get('Digest') or ''
    return meta,digest

def latest_ghcr(ref:str)->tuple[str,str]:
    if os.environ.get("SUGARKUBE_APP_CHART_LATEST"):
        return os.environ["SUGARKUBE_APP_CHART_LATEST"], ""
    m=re.match(r"oci://ghcr\.io/([^/]+)/(.+)", ref)
    if not m: return '', 'latest unknown: unsupported chart registry; inspect manually with helm/oras.'
    owner, package=m.group(1), m.group(2)
    pkg=package.replace('/','%2F')
    url=f"https://api.github.com/users/{owner}/packages/container/{pkg}/versions?per_page=100"
    token=os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    req=urllib.request.Request(url, headers={"Accept":"application/vnd.github+json", **({"Authorization":f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp: data=json.load(resp)
    except Exception as e:
        return '', f"latest unknown: GHCR API lookup unavailable ({e}). Check https://github.com/{owner}?tab=packages or run: gh api {url}"
    versions=[]
    for item in data:
        for tag in item.get('metadata',{}).get('container',{}).get('tags',[]) or []:
            t=tag[10:] if tag.startswith('tokenplace-') else tag
            if SEMVER.match(t): versions.append(t)
    if not versions: return '', 'latest unknown: no semver tags found in GHCR API response.'
    versions=sorted(set(versions), key=lambda s: tuple(map(int, SEMVER.match(s).groups()[:3])))
    return versions[-1], ''

def cmp(a,b):
    ma,mb=SEMVER.match(a),SEMVER.match(b)
    if not ma or not mb: return 0
    return (tuple(map(int,ma.groups())) > tuple(map(int,mb.groups()))) - (tuple(map(int,ma.groups())) < tuple(map(int,mb.groups())))

def status(args):
    cfg=app_config.load_config(args.app,'staging',args.config or None)
    pin_file=cfg.get('SUGARKUBE_VERSION_FILE','')
    ver=cfg.get('SUGARKUBE_VERSION') or read_pin(pin_file)
    meta,digest=chart_meta(cfg['SUGARKUBE_CHART'],ver)
    print(f"app: {cfg['SUGARKUBE_APP']}")
    print(f"chart ref: {cfg['SUGARKUBE_CHART']}")
    print(f"pinned version: {ver}")
    print(f"chart appVersion: {meta.get('appVersion','unknown')}")
    print(f"chart digest: {digest or 'unknown'}")
    print(f"pin file: {pin_file}")
    latest,msg=latest_ghcr(cfg['SUGARKUBE_CHART'])
    if latest:
        print(f"latest version: {latest}")
        if cmp(ver,latest)<0:
            print(f"WARNING: Pinned chart appears stale: {ver} < {latest}")
            print(f"Run: just app-chart-bump app={cfg['SUGARKUBE_APP']} version={latest}")
    else: print(msg)

def bump(args):
    version=(args.version or '').strip()
    while version.startswith("version="):
        version = version[len("version="):].strip()
    if not version: raise SystemExit('ERROR: version must not be empty. Use version=<semver>.')
    cfg=app_config.load_config(args.app,'staging',args.config or None)
    pin_file=cfg.get('SUGARKUBE_VERSION_FILE','')
    if not pin_file: raise SystemExit('ERROR: app config must use SUGARKUBE_VERSION_FILE for bumping.')
    chart_meta(cfg['SUGARKUBE_CHART'], version)
    p=ROOT/pin_file
    lines=p.read_text().splitlines()
    replaced=False; out=[]
    for line in lines:
        if not replaced and line.split('#',1)[0].strip(): out.append(version); replaced=True
        else: out.append(line)
    if not replaced: out.append(version)
    p.write_text('\n'.join(out)+'\n')
    subprocess.run(['git','diff','--',pin_file], cwd=ROOT, check=False)
    print('\nNext steps:')
    print(f'git add {pin_file}')
    print(f'git commit -m "Bump {cfg["SUGARKUBE_APP"]} chart pin to {version}"')
    print('git push')
    print(f'just app-deploy app={cfg["SUGARKUBE_APP"]} env=staging tag=<APP_TAG>')

def preflight(args):
    cfg=app_config.load_config(args.app,args.env,args.config or None); ver=cfg.get('SUGARKUBE_VERSION') or read_pin(cfg.get('SUGARKUBE_VERSION_FILE',''))
    tag=app_config.resolve_tag(cfg,args.tag,prod_fallback=False)
    print(f"app: {cfg['SUGARKUBE_APP']}\nenv: {cfg['SUGARKUBE_ENV']}\nimage tag: {tag}\nchart ref: {cfg['SUGARKUBE_CHART']}\nchart version: {ver}\nchart pin: {cfg.get('SUGARKUBE_VERSION_FILE','<inline>')}")
    chart_meta(cfg['SUGARKUBE_CHART'],ver)
    req=REQ_ENV.get(cfg['SUGARKUBE_APP'],[])
    if req:
        cmd=['helm','template',cfg['SUGARKUBE_RELEASE'],cfg['SUGARKUBE_CHART'],'--namespace',cfg['SUGARKUBE_NAMESPACE'],'--version',ver]
        for vf in cfg['SUGARKUBE_VALUES'].split(','): cmd += ['-f', vf.strip()]
        cmd += ['--set', f'image.tag={tag}']
        cp=run(cmd)
        if cp.returncode: raise SystemExit(cp.stderr or cp.stdout)
        missing=[x for x in req if x not in cp.stdout]
        if missing:
            print(f"ERROR: rendered {cfg['SUGARKUBE_APP']} manifest is missing required env vars: {', '.join(missing)}", file=sys.stderr)
            print(f"Pinned chart version: {ver} ({cfg.get('SUGARKUBE_VERSION_FILE','<inline>')})", file=sys.stderr)
            print(f"Run: just app-chart-status app={cfg['SUGARKUBE_APP']}", file=sys.stderr)
            print(f"Then bump explicitly: just app-chart-bump app={cfg['SUGARKUBE_APP']} version=<published-version>", file=sys.stderr)
            return 1
    return 0

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    for c in ('status','bump','preflight'):
        s=sub.add_parser(c); s.add_argument('--app',required=True); s.add_argument('--config',default='')
        if c in ('bump',): s.add_argument('--version',required=True)
        if c in ('preflight',): s.add_argument('--env',required=True); s.add_argument('--tag',required=True)
    a=p.parse_args(); return {'status':status,'bump':bump,'preflight':preflight}[a.cmd](a) or 0
if __name__=='__main__': raise SystemExit(main())
