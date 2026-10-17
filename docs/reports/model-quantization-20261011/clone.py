"""只管理本次 18314 验收容器；业务配置与只读 JAR 来源保持一致。"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent
NAME='rs-quantization-20261011-agent'
SOURCE='rs-e2e-857e8b14-agent-fast'


def configure(model_port):
    current=subprocess.run(['docker','inspect',NAME],capture_output=True,text=True)
    if current.returncode==0:
        data=json.loads(current.stdout)[0]
        env=dict(x.split('=',1) for x in data['Config']['Env'] if '=' in x)
        assert env.get('SERVER_PORT')=='18314', '同名容器不属于本次验收'
        assert data['HostConfig']['NetworkMode']=='host'
        assert (ROOT/'agent-clone-state.json').exists()
        subprocess.run(['docker','stop',NAME],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','rm',NAME],check=True,stdout=subprocess.DEVNULL)
    else:
        data=json.loads(subprocess.check_output(['docker','inspect',SOURCE],text=True))[0]
        env=dict(x.split('=',1) for x in data['Config']['Env'] if '=' in x)
    env.update(SERVER_PORT='18314',SERVER_ADDRESS='127.0.0.1',
               RS_AGENT_OPENAI_BASE_URL=f'http://127.0.0.1:{model_port}/v1')
    envfile=ROOT/'agent-clone.private.env'
    envfile.write_text('\n'.join(k+'='+v for k,v in env.items())+'\n');envfile.chmod(0o600)
    command=['docker','run','-d','--name',NAME,'--network','host','--memory','3g',
             '--label','rsagent.quantization-task=20261011','--env-file',str(envfile)]
    for mount in data['Mounts']:
        assert not mount['RW']
        command+=['--mount','type=bind,src='+mount['Source']+',dst='+mount['Destination']+',readonly']
    command+=[data['Config']['Image']]+data['Config']['Cmd']
    subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    (ROOT/'agent-clone-state.json').write_text(json.dumps({'name':NAME,'port':18314,'model_port':model_port,
                  'image':data['Config']['Image'],'jar_sources':[m['Source'] for m in data['Mounts']]},indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--model-port',type=int,choices=[18082,18092,18094],required=True)
    configure(parser.parse_args().model_port)
