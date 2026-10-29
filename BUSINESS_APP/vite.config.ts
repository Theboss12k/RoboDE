import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(({mode})=>({plugins:[react()],base:'/business/',server:{proxy:{'/api':mode==='test'?'http://127.0.0.1:8876':'http://127.0.0.1:8765'}},build:{chunkSizeWarningLimit:1800}}));
