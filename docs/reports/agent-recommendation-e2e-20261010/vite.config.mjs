import original from '../../../java_agent/frontend/vite.config.ts';
export default {
  ...original,
  server: { host: '127.0.0.1', port: 18289, strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:18288', changeOrigin: true } } },
};
