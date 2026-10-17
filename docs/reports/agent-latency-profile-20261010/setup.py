"""创建新的隔离环境，业务 JAR 不变，只挂载可移除的计时 Java Agent。"""
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ROOT = '/tmp/rs-agent-e2e-20261010-profile-1600'
OLD = '/tmp/rs-agent-e2e-20261010-pool-1400'

def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, encoding='utf-8', **kwargs)

if __name__ == '__main__':
    build = Path(tempfile.mkdtemp(prefix='rs-latency-profiler-'))
    java = Path(os.environ['JAVA_HOME']) / 'bin'
    exports = ['--add-exports=java.base/jdk.internal.org.objectweb.asm=ALL-UNNAMED',
               '--add-exports=java.base/jdk.internal.org.objectweb.asm.commons=ALL-UNNAMED']
    run([str(java / 'javac.exe'), *exports, '-d', str(build), str(HERE / 'LatencyAgent.java')])
    manifest = build / 'MANIFEST.MF'
    manifest.write_text('Manifest-Version: 1.0\nPremain-Class: rs.profile.LatencyAgent\n\n')
    jar = build / 'latency-agent.jar'
    run([str(java / 'jar.exe'), 'cfm', str(jar), str(manifest), '-C', str(build), 'rs'])
    env = (HERE.parent / 'agent-persistence-optimization-20261010/environment.py').read_text(encoding='utf-8')
    env = env.replace('    creds = json.loads', '    creds = json.loads')
    # 双版本服务不启动；此次只测已优化的最新业务构建。
    env = env.replace('    parser = argparse.ArgumentParser()',
                      "    MODULES.pop('agent-base', None); MODULES.pop('recommend-base', None)\n    parser = argparse.ArgumentParser()")
    env = env.replace('            if label == "agent-base":',
        '            if label in ("agent-fast", "recommend-fast", "user", "model") and os.environ.get("RS_PROFILE_ENABLED", "true") == "true":\n'
        '                env["JAVA_OPTS"] += " --add-exports=java.base/jdk.internal.org.objectweb.asm=ALL-UNNAMED --add-exports=java.base/jdk.internal.org.objectweb.asm.commons=ALL-UNNAMED -javaagent:/app/latency-agent.jar"\n'
        '            if label == "agent-base":')
    env = env.replace('"eclipse-temurin:21-jre",',
                      '"-v", str(root / "latency-agent.jar") + ":/app/latency-agent.jar:ro", "eclipse-temurin:21-jre",')
    env = env.replace('            jdbc = f"jdbc:mysql://127.0.0.1:13306/',
                      '            jdbc_port = 18306 if label in ("agent-fast", "recommend-fast", "user") and os.environ.get("RS_PROFILE_STORAGE") == "nvme" else 13306\n'
                      '            jdbc = f"jdbc:mysql://127.0.0.1:{jdbc_port}/')
    (HERE / 'environment.py').write_text(env, encoding='utf-8')
    probe = (HERE.parent / 'agent-persistence-optimization-20261010/probe.py').read_text(encoding='utf-8')
    probe = probe.replace(OLD, ROOT).replace('    start = time.perf_counter()\n    events',
                '    start_epoch_ms = time.time() * 1000\n    start = time.perf_counter()\n    events')
    probe = probe.replace("'agent_done_ms': round(agent_ms, 2),", "'start_epoch_ms': start_epoch_ms, 'agent_done_ms': round(agent_ms, 2),")
    (HERE / 'probe.py').write_text(probe, encoding='utf-8')
    remote = f"""from pathlib import Path
import shutil
root=Path({ROOT!r});old=Path({OLD!r})
assert not root.exists(), 'allocate a fresh root'
root.mkdir()
for path in old.iterdir():
    if path.name.endswith('.sql') or path.name.endswith('.cql') or path.name in ('bge_m3_embedding_server.py', 'start_bge.py', 'stop_bge.py'):
        if path.suffix == '.py': (root/path.name).write_text(path.read_text().replace({OLD!r}, {ROOT!r}))
        else: shutil.copy2(path,root/path.name)
for module in ('catalog','model','user','platform-trace'):
    shutil.copy2(old/('rs-service-'+module+'.jar'),root/('rs-service-'+module+'.jar'))
shutil.copy2(old/'rs-api-gateway.jar',root/'rs-api-gateway.jar')
print('fresh QA root allocated')
"""
    run(['ssh', 'server', 'python3 -'], input=remote)
    files = [HERE / 'environment.py', HERE / 'probe.py', jar,
             REPO / 'java_agent/rs-service-agent/target/rs-service-agent.jar',
             REPO / 'java_agent/rs-service-recommend/target/rs-service-recommend.jar']
    evidence = {}
    for file in files:
        name = file.name.replace('-0.1.0-SNAPSHOT', '')
        run(['scp', str(file), 'server:' + ROOT + '/' + name])
        if file.suffix == '.jar': evidence[name] = hashlib.sha256(file.read_bytes()).hexdigest()
    (HERE / 'artifacts.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print('profiling tool compiled; unchanged business artifacts uploaded')
