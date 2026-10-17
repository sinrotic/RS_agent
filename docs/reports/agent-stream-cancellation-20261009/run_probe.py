#!/usr/bin/env python3
"""在服务器的独立探针目录解包已上传 JAR 并运行，不启动或重启模型服务。"""
from pathlib import Path
import json
import os
import subprocess
from zipfile import ZipFile


directory = Path(__file__).resolve().parent
runtime = directory / "runtime"
runtime.mkdir(exist_ok=True)
with ZipFile(directory / "rs-service-agent.jar") as archive:
    for entry in archive.infolist():
        if entry.is_dir() or not entry.filename.startswith(("BOOT-INF/classes/", "BOOT-INF/lib/")):
            continue
        target = (runtime / entry.filename).resolve()
        if not target.is_relative_to(runtime.resolve()):
            raise RuntimeError("JAR 目标路径超出临时目录")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(entry))

classpath = os.pathsep.join(map(str, [directory, runtime / "BOOT-INF/classes",
    *sorted((runtime / "BOOT-INF/lib").glob("*.jar")),
    directory / "spring-boot-test-4.0.3.jar", directory / "assertj-core-3.27.7.jar"]))
compiled = subprocess.run(["javac", "-proc:none", "-encoding", "UTF-8", "-cp", classpath, "-d", str(directory),
    str(directory / "ModelStreamCancellationProbe.java")])
if compiled.returncode:
    raise SystemExit(compiled.returncode)
print("开始 GPU 1 模型流停止探针，Java 堆限制 512 MiB。", flush=True)
with (directory / "probe.log").open("w") as log:
    result = subprocess.run(["java", "-Xmx512m", "-cp", classpath, "ModelStreamCancellationProbe",
        "http://127.0.0.1:18082", str(directory / "gpu1.json")], stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    print((directory / "probe.log").read_text()[-5000:])
    raise SystemExit(result.returncode)
report = json.loads((directory / "gpu1.json").read_text())
for sample in report["samples"]:
    print(json.dumps({k: v for k, v in sample.items() if k != "observations"}, ensure_ascii=False), flush=True)
