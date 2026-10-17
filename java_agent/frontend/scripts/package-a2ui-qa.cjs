// 构建产物与源文件哈希清单；不包含运行密钥或账号凭证。
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const target = path.resolve(process.argv[2]);
if (fs.existsSync(target)) throw new Error('发布目录已存在，拒绝覆盖');
fs.mkdirSync(target, { recursive: true });
fs.cpSync(path.join(root, 'dist'), path.join(target, 'dist'), { recursive: true });
fs.copyFileSync(path.join(__dirname, 'a2ui-qa-nginx.conf'), path.join(target, 'nginx.conf'));
fs.copyFileSync(path.join(__dirname, 'deploy-a2ui-qa.py'), path.join(target, 'deploy.py'));
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const files = {};
const visit = dir => fs.readdirSync(dir, { withFileTypes: true }).forEach(entry => {
  const file = path.join(dir, entry.name);
  if (entry.isDirectory()) visit(file);
  else files[path.relative(target, file).split(path.sep).join('/')] = hash(file);
});
visit(target);
const sources = {};
for (const source of ['src/views/AgentChat.tsx', 'src/components/A2uiView.tsx', 'src/utils/a2ui.ts',
  'src/utils/agentUiProjection.ts', 'src/api/agentClient.ts', 'src/api/shared.ts', 'package.json', 'package-lock.json']) {
  sources[source] = hash(path.join(root, source));
}
fs.writeFileSync(path.join(target, 'manifest.json'), JSON.stringify({ built_at_utc: new Date().toISOString(), files, sources }, null, 2));
console.log(JSON.stringify({ release_dir: target, index_sha256: files['dist/index.html'] }));
