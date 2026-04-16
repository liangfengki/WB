import { defineConfig } from 'vite';
import legacy from '@vitejs/plugin-legacy';

export default defineConfig({
    root: '../',
    publicDir: 'public',
    build: {
        outDir: 'dist',
        emptyOutDir: true,
        rollupOptions: {
            input: {
                main: '/index.html',
                admin: '/admin.html',
            },
        },
        minify: 'terser',
        terserOptions: {
            compress: {
                drop_console: true,
                drop_debugger: true,
            },
        },
        cssMinify: true,
        reportCompressedSize: true,
    },
    plugins: [
        legacy({
            targets: ['> 0.5%', 'last 2 versions', 'not dead'],
        }),
    ],
    server: {
        port: 3000,
        proxy: {
            '/api': {
                target: 'http://127.0.0.1:5010',
                changeOrigin: true,
            },
        },
    },
});
