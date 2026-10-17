"""在远程 Linux 主机冷迁移 MySQL 提交存储；默认只预检，--apply 才变更。

已有 rs_agent 库保留在原盘，先冷备整个实例。保留所有 MySQL 持久化设置。
切换后的回退必须停写并使用完整冷备，不能直接拼接已发生写入的旧文件。
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time


NAME = "rs-agent-java-mysql"
GIB = 1024 ** 3


def run(command, data=None, timeout=120):
    result = subprocess.run(command, input=data, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        # 不把 Compose 展开后的凭证写入日志。
        raise RuntimeError(f"命令失败: {command[:2]} (exit={result.returncode})")
    return result.stdout.strip()


def inspect():
    return json.loads(run(["docker", "inspect", NAME]))[0]


def sql(statement):
    return run(["docker", "exec", "-i", NAME, "sh", "-c",
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B'], statement)


def ready():
    for _ in range(90):
        try:
            sql("SELECT 1;")
            return
        except RuntimeError:
            time.sleep(1)
    raise RuntimeError("MySQL 启动检查超时")


def evidence():
    variables = sql("SELECT @@server_uuid,@@innodb_flush_log_at_trx_commit,@@sync_binlog,"
                    "@@log_bin,@@innodb_doublewrite,@@innodb_flush_method;")
    tables = sql("SELECT table_name FROM information_schema.tables WHERE table_schema='rs_agent' "
                 "AND table_type='BASE TABLE' ORDER BY table_name;").splitlines()
    counts = {}
    for table in tables:
        if not re.fullmatch(r"\w+", table):
            raise ValueError("无法安全核验表名")
        # 大型导入表核验冷备文件；在线业务表核验精确行数。
        if not table.startswith("amazon_"):
            counts[table] = int(sql(f"SELECT COUNT(*) FROM rs_agent.`{table}`;"))
    return {"durability": variables, "tables": tables, "business_row_counts": counts}


def atomic_text(path, content):
    temporary = path.with_name(path.name + ".migration-tmp")
    temporary.write_text(content)
    temporary.chmod(0o600)
    temporary.replace(path)


def set_env(content, values):
    for key, value in values.items():
        pattern = rf"(?m)^{re.escape(key)}=.*$"
        content = re.sub(pattern, key + "=" + value, content) if re.search(pattern, content) else content.rstrip() + "\n" + key + "=" + value + "\n"
    return content


def hashes(image, directory, exclude_business=False):
    find = ["find", "/data", "-type", "f"]
    if exclude_business:
        find += ["!", "-path", "/data/rs_agent/*"]
    output = run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "find",
                  "--mount", f"type=bind,source={directory},target=/data,readonly", image,
                  *find[1:], "-exec", "sha256sum", "{}", "+"], timeout=1800)
    result = {}
    for line in output.splitlines():
        digest, filename = line.split("  ", 1)
        assert re.fullmatch(r"[0-9a-f]{64}", digest) and filename.startswith("/data/")
        result[filename.removeprefix("/data/")] = digest
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--infra-dir", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=Path("/var/lib/rs-agent-java/mysql-nvme-20261010"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--resume-record", type=Path, help="仅续跑尚未切换配置、源文件仍与冷备完全一致的记录")
    args = parser.parse_args()
    infra = args.infra_dir.resolve()
    target = args.target
    # 容器以 root 创建此项目目录；禁止借路径或符号链接写入其他位置。
    if str(target.parent) != "/var/lib/rs-agent-java" or not re.fullmatch(r"mysql-nvme-[0-9]+", target.name):
        raise ValueError("目标必须位于 /var/lib/rs-agent-java/mysql-nvme-日期")
    if target.exists() or target.is_symlink():
        raise ValueError("目标已存在，拒绝覆盖")
    info = inspect()
    if info["State"]["Running"]:
        raise ValueError("请先停止业务服务及 MySQL，保证没有并发写入")
    active = run(["docker", "ps", "--format", "{{.Names}}"]).splitlines()
    if any(name.startswith("rs-agent-java-service-") or name == "rs-agent-java-api-gateway" for name in active):
        raise ValueError("业务服务仍在运行")
    source = Path(next(m["Source"] for m in info["Mounts"] if m["Destination"] == "/var/lib/mysql"))
    if any(m["Destination"].startswith("/var/lib/mysql/") for m in info["Mounts"]):
        raise ValueError("已有分层数据挂载，不能只复制主目录；需核对全部数据目录后另行迁移")
    device = run(["findmnt", "-n", "-o", "SOURCE", "-T", str(target.parent.parent)])
    if not re.fullmatch(r"/dev/nvme[0-9]+n[0-9]+p[0-9]+", device):
        raise ValueError("目标分区不是已挂载的 NVMe")
    if target.parent.exists() and target.parent.resolve() != target.parent:
        raise ValueError("目标父目录包含符号链接")
    image = info["Image"]  # 使用同一镜像摘要，避免物理副本跨版本打开。
    base = ["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh",
            "--mount", f"type=bind,source={source},target=/source,readonly"]
    sizes = run(base + [image, "-c", "du -lsk /source /source/rs_agent"]).splitlines()
    size, business_size = [int(line.split()[0]) * 1024 for line in sizes]
    free = os.statvfs("/var/lib").f_bavail * os.statvfs("/var/lib").f_frsize
    backup = source.parent / ("mysql-cold-backup-" + time.strftime("%Y%m%d%H%M%S"))
    backup_free = os.statvfs(source.parent).f_bavail * os.statvfs(source.parent).f_frsize
    if free - (size - business_size) < 8 * GIB or backup_free < size + 8 * GIB:
        raise ValueError("目标或冷备分区没有足够余量")
    plan = {"source": str(source), "target": str(target), "legacy_database_dir": str(source / "rs_agent"),
            "nvme_device": device, "original_bytes": size, "nvme_copy_bytes": size - business_size,
            "nvme_available_bytes": free, "cold_backup": str(backup), "image_id": image}
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if not args.apply:
        return
    compose_path = infra / "docker-compose.yml"
    env_path = infra / ".env"
    original_compose, original_env = compose_path.read_text(), env_path.read_text()
    if original_compose.count("../db/mysql:/var/lib/mysql") != 1:
        raise ValueError("Compose 数据挂载与预期不一致，请先检查，拒绝猜测替换")
    if re.search(r"(?m)^COMPOSE_FILE=", original_env):
        raise ValueError("已有 Compose 组合，需要人工合并后再迁移")
    if args.resume_record:
        record = args.resume_record.resolve()
        assert record.parent == infra and re.fullmatch(r"mysql-migration-[0-9]+", record.name)
        saved_plan = json.loads((record / "plan.json").read_text())
        assert all(saved_plan[key] == plan[key] for key in ("source", "target", "image_id"))
        assert original_compose == (record / "docker-compose.before.yml").read_text()
        assert original_env == (record / "env.before").read_text()
        backup = Path(saved_plan["cold_backup"])
        assert backup.parent == source.parent and re.fullmatch(r"mysql-cold-backup-[0-9]+", backup.name)
        plan["cold_backup"] = str(backup)
    else:
        record = infra / ("mysql-migration-" + time.strftime("%Y%m%d%H%M%S"))
        record.mkdir(mode=0o700)
        atomic_text(record / "docker-compose.before.yml", original_compose)
        atomic_text(record / "env.before", original_env)
        (record / "plan.json").write_text(json.dumps(plan, indent=2))
    changed = False
    backup_verified = False
    try:
        if args.resume_record:
            before = json.loads((record / "before.json").read_text())
        else:
            run(["docker", "start", NAME]); ready()
            before = evidence()
            (record / "before.json").write_text(json.dumps(before, indent=2))
            run(["docker", "stop", "--time", "90", NAME], timeout=120)
            if inspect()["State"]["ExitCode"] != 0:
                raise RuntimeError("MySQL 未正常退出，取消冷迁移")
            backup.mkdir(mode=0o700)
            print("开始完整冷备", flush=True)
            run(base + ["--mount", f"type=bind,source={backup},target=/backup", image, "-c",
                        "cp -a /source/. /backup/"], timeout=2400)
        print("核验冷备所有文件 SHA-256", flush=True)
        source_hashes = hashes(image, source)
        assert hashes(image, backup) == source_hashes, "冷备不完整或源数据已变化，拒绝切换"
        backup_verified = True
        print("冷备核验通过，复制 NVMe 控制文件", flush=True)
        run(base + ["-v", "/var/lib/rs-agent-java:/ssd", image, "-c",
                    f"test ! -e /ssd/{target.name} && mkdir /ssd/{target.name} && "
                    f"find /source -mindepth 1 -maxdepth 1 ! -name rs_agent -exec cp -a -t /ssd/{target.name} {{}} + && "
                    f"chown --reference=/source /ssd/{target.name} && chmod --reference=/source /ssd/{target.name}"], timeout=120)
        assert hashes(image, target) == {name: digest for name, digest in source_hashes.items() if not name.startswith("rs_agent/")}
        override = Path(__file__).with_name("docker-compose.mysql-hybrid.yml")
        if override.parent.resolve() != infra:
            atomic_text(infra / override.name, override.read_text())
        atomic_text(compose_path, original_compose.replace("../db/mysql:/var/lib/mysql", "${RS_MYSQL_DATA_DIR:-../db/mysql}:/var/lib/mysql"))
        atomic_text(env_path, set_env(original_env, {
            "RS_MYSQL_DATA_DIR": str(target), "RS_MYSQL_LEGACY_DATABASE_DIR": str(source / "rs_agent"),
            "COMPOSE_FILE": "docker-compose.yml:docker-compose.mysql-hybrid.yml"}))
        changed = True
        assert json.loads(run(["docker", "image", "inspect", info["Config"]["Image"]]))[0]["Id"] == image, "镜像标签已变化，取消切换"
        compose = ["docker", "compose", "--env-file", str(env_path), "--project-directory", str(infra),
                   "-f", str(compose_path), "-f", str(infra / override.name)]
        run(compose + ["up", "-d", "--no-deps", "--pull", "never", "mysql"])
        ready()
        after = evidence()
        if after != before:
            raise RuntimeError("冷迁移前后业务行数、表名或落盘配置不一致")
        mounts = inspect()["Mounts"]
        assert any(m["Source"] == str(target) and m["Destination"] == "/var/lib/mysql" for m in mounts)
        assert any(m["Source"] == str(source / "rs_agent") and m["Destination"] == "/var/lib/mysql/rs_agent" for m in mounts)
        # 跨两次重启再核验，避免只验证首次启动。
        run(["docker", "restart", "--time", "90", NAME]); ready()
        assert evidence() == before
        run(["docker", "stop", "--time", "90", NAME], timeout=120)
        result = {**plan, "before": before, "after": after, "cold_backup_byte_comparison": True,
                  "restart_verified": True, "restored_stopped_state": True, "private_record": str(record),
                  "verified_file_count": len(source_hashes), "cold_backup_verification": "SHA-256"}
        (record / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print("迁移完成，MySQL 恢复原来的停止状态；核验记录: " + str(record / "result.json"), flush=True)
    except Exception:
        if inspect()["State"]["Running"]:
            run(["docker", "stop", "--time", "90", NAME], timeout=120)
        if changed:
            # 启动新实例会修改共享业务表；回退也必须恢复同一次冷备中的整个实例。
            if not backup_verified:
                raise RuntimeError("没有通过核验的冷备，拒绝自动回退")
            preserved = source.with_name("mysql-failed-migration-" + time.strftime("%Y%m%d%H%M%S"))
            source.rename(preserved)
            source.mkdir(mode=0o700)
            run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh",
                 "--mount", f"type=bind,source={backup},target=/backup,readonly",
                 "--mount", f"type=bind,source={source},target=/restored", image, "-c",
                 "cp -a /backup/. /restored/ && chown --reference=/backup /restored && "
                 "chmod --reference=/backup /restored"], timeout=2400)
            assert hashes(image, source) == source_hashes
            atomic_text(compose_path, original_compose)
            atomic_text(env_path, original_env)
            run(["docker", "compose", "--env-file", str(env_path), "--project-directory", str(infra),
                 "-f", str(compose_path), "up", "-d", "--no-deps", "--pull", "never", "mysql"])
            ready()
            assert evidence() == before
            run(["docker", "stop", "--time", "90", NAME], timeout=120)
            print("已用完整冷备恢复原实例并重新核验；保留迁移数据和失败现场。", flush=True)
        raise


if __name__ == "__main__":
    main()
