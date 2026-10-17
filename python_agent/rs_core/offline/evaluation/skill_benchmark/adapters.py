"""本地已构建 Java Agent 的启动命令；不启动生产 HTTP 服务。"""

import os
import shutil
import subprocess
import zipfile
from pathlib import Path


def prepare_java_command(repo_root, java="java"):
    root = Path(repo_root).resolve()
    target = root / "java_agent/rs-service-agent/target"
    harness = target / "test-classes/com/sinrotic/rs/agent/benchmark/SkillBenchmarkMain.class"
    jar = target / "rs-service-agent.jar"
    if not harness.is_file() or not jar.is_file():
        raise ValueError("请先用 JDK21 执行 Maven package/test-compile，构建 Agent 和评测入口")
    version = subprocess.run([str(java), "-version"], capture_output=True, text=True, check=False)
    import re

    match = re.search(r'version "(\d+)', version.stderr + version.stdout)
    if version.returncode or not match or int(match.group(1)) < 21:
        raise ValueError("评测入口需要 JDK21+，请通过 --java 指定 java 可执行文件")
    # Spring Boot 已打包依赖作为本地只读来源，无需安装 SNAPSHOT 到 ~/.m2。
    stat = jar.stat()
    library_dir = target / f"skill-benchmark-libs-{stat.st_size}-{stat.st_mtime_ns}"
    library_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(jar) as archive:
        for entry in archive.infolist():
            if not entry.filename.startswith("BOOT-INF/lib/") or not entry.filename.endswith(
                ".jar"
            ):
                continue
            destination = library_dir / Path(entry.filename).name
            if destination.is_file() and destination.stat().st_size == entry.file_size:
                continue
            with archive.open(entry) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
    classpath = os.pathsep.join(
        str(path)
        for path in (
            target / "test-classes",
            target / "classes",
            root / "java_agent/rs-common/target/classes",
            library_dir / "*",
        )
    )
    return [
        str(java),
        "-Xmx1024m",
        "-cp",
        classpath,
        "com.sinrotic.rs.agent.benchmark.SkillBenchmarkMain",
    ]
