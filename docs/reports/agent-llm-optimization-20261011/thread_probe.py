"""只检查自有 QA JVM 的阻塞位置，导出方法栈，不导出线程局部业务内容。"""
import json
from pathlib import Path
import subprocess
from probe import ROOT

state=json.loads((ROOT/'state.json').read_text()); name=state['agent-fast']
assert name=='rs-e2e-'+state['suffix']+'-agent-fast'
inspect=json.loads(subprocess.check_output(['docker','inspect',name],text=True))[0]
pid=inspect['State']['Pid'];assert pid>0
jcmd=Path(subprocess.check_output(['readlink','-f','/usr/bin/jcmd'],text=True).strip())
jdk=jcmd.parent.parent;assert str(jdk).startswith('/usr/lib/jvm/')
file='/tmp/rs-llm-thread-probe.json'
process=subprocess.run(['docker','run','--rm','--name','rs-e2e-'+state['suffix']+'-thread-probe',
    '--network','none','--pid','host','-v',str(jdk)+':/jdk:ro',
    'eclipse-temurin:21-jre','/jdk/bin/jcmd',str(pid),'Thread.dump_to_file','-format=json',file],
    text=True,capture_output=True,timeout=30)
assert process.returncode==0,process.stderr[-500:]
raw=subprocess.check_output(['docker','exec',name,'cat',file],text=True)
dump=json.loads(raw);results=[]
def scan(node):
    if isinstance(node,dict):
        stack=node.get('stack')
        if isinstance(stack,list) and any(any(term in frame for term in ('AgentLoop','SpringAiAgent','StreamingAgent','HttpAgent','JavaNetAgent','AgentCapability')) for frame in stack):
            results.append({'tid':node.get('tid'), 'stack':stack[:30]})
        for value in node.values():scan(value)
    elif isinstance(node,list):
        for value in node:scan(value)
scan(dump)
(ROOT/'thread-probe.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
subprocess.run(['docker','exec',name,'rm','--',file],check=True)
print(json.dumps(results,ensure_ascii=False,indent=2),flush=True)
